import os
import tempfile
import requests
from flask import Blueprint, jsonify, send_file
from PIL import Image, ImageFilter

from .text_redaction import redact_caption

remediate_bp = Blueprint("remediate_content", __name__)

CONTENT_DRAFTS_SERVICE_URL = os.environ.get("CONTENT_DRAFTS_SERVICE_URL", "http://CONTENT_DRAFTS:5002")
DETECTIONS_SERVICE_URL = os.environ.get("DETECTIONS_SERVICE_URL", "http://DETECTIONS:5003")
EDITS_SERVICE_URL = os.environ.get("EDITS_SERVICE_URL", "http://EDITS:5004")
UPLOAD_POST_SERVICE_URL = os.environ.get("UPLOAD_POST_SERVICE_URL", "http://UPLOAD_POST:5014")

# Anchored to an absolute path rather than left relative — relative paths
# resolve against the process's current working directory, which turned out
# not to be reliably consistent between requests under the dev server.
SERVICE_ROOT = os.environ.get("SERVICE_ROOT", "/service")
OUTPUT_DIR = os.path.join(SERVICE_ROOT, "storage", "remediated")


def _get_draft(draft_id):
    resp = requests.get(f"{CONTENT_DRAFTS_SERVICE_URL}/drafts/{draft_id}")
    if resp.status_code == 404:
        return None, (jsonify({"error": "draft not found"}), 404)
    if resp.status_code != 200:
        return None, (jsonify({"error": "failed to fetch draft"}), 502)
    return resp.json(), None


def _get_original_path(draft_id):
    """Downloads the draft's original file from upload_post into a local temp
    file and returns its path. upload_post is the only service that ever
    writes this file to local disk — as separate Render services (no shared
    draft_storage volume outside Docker Compose), the bytes have to cross the
    network instead of being read off a shared path. Re-fetched fresh on
    every call rather than cached, since this runs infrequently (propose /
    confirm / revert / restore / download) and staying stateless avoids any
    risk of a stale or missing temp file between requests."""
    draft, error = _get_draft(draft_id)
    if error:
        return None, error
    storage_path = draft.get("storage_path")
    if not storage_path:
        return None, (jsonify({"error": "draft has no stored file"}), 400)

    resp = requests.get(f"{UPLOAD_POST_SERVICE_URL}/drafts/{draft_id}/original")
    if resp.status_code != 200:
        return None, (jsonify({"error": "original file not found"}), 404)

    filename = os.path.basename(storage_path)
    tmp_path = os.path.join(tempfile.gettempdir(), f"{draft_id}_{filename}")
    with open(tmp_path, "wb") as f:
        f.write(resp.content)
    return tmp_path, None


def apply_remediation(original_path, edits):
    """Blur each region that has a box. Returns output path. Whatever extension
    the original has is preserved, since the output name is derived from it."""
    img = Image.open(original_path)

    for e in edits:
        region = e.get("region_affected")
        if region:
            box = (region["x"], region["y"],
                   region["x"] + region["w"], region["y"] + region["h"])
            blurred = img.crop(box).filter(ImageFilter.GaussianBlur(radius=15))
            img.paste(blurred, box)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, os.path.basename(original_path))
    img.save(out_path)  # not passing exif= strips the GPS/EXIF on save
    return out_path


def _regenerate_output(draft_id):
    """Rebuilds the remediated file from the original using only the edits
    currently marked 'applied'. Must be called any time the applied set
    changes (confirm/revert/restore) so the downloadable file always matches
    the edits' current state rather than whatever was baked in at first confirm."""
    original_path, error = _get_original_path(draft_id)
    if error:
        return None, error
    if not os.path.exists(original_path):
        return None, (jsonify({"error": "original file not found"}), 404)

    resp = requests.get(f"{EDITS_SERVICE_URL}/drafts/{draft_id}/edits")
    if resp.status_code != 200:
        return None, (jsonify({"error": "failed to fetch edits"}), 502)
    applied = [e for e in resp.json() if e["status"] == "applied"]

    return apply_remediation(original_path, applied), None


@remediate_bp.route("/drafts/<draft_id>/remediate", methods=["POST"])
def remediate_content(draft_id):
    # No score filter here: when scan_draft calls this directly, every
    # detection present is already <=3 by construction (it only reaches here
    # when nothing scored >=4). When quarantine_high_risk's "edit" action
    # calls this instead, the detections ARE the >=4 finding(s) that caused
    # the hold in the first place — filtering those out left this route with
    # nothing to do and "edit" permanently broken for quarantined items.
    resp = requests.get(f"{DETECTIONS_SERVICE_URL}/drafts/{draft_id}/detections")
    if resp.status_code != 200:
        return jsonify({"error": "failed to fetch detections"}), 502
    detections = resp.json()
    if not detections:
        return jsonify({"error": "nothing to remediate"}), 400

    # text leaks (phone numbers, addresses, birthdates in a caption) need the
    # user to edit their caption, not an image blur/strip — pulled out here
    # instead of falling through to "no bounding_region -> metadata_strip",
    # which would create a bogus image edit for a detection with no image.
    text_detections = [d for d in detections if d.get("source_type") == "text"]
    image_detections = [d for d in detections if d.get("source_type") != "text"]

    # only fetch the draft if there's actually image or text work to do
    draft = None
    if image_detections or text_detections:
        draft, error = _get_draft(draft_id)
        if error:
            return error

    original_path = None
    if image_detections:
        storage_path = draft.get("storage_path")
        if not storage_path:
            return jsonify({"error": "draft has no stored file"}), 400
        original_path = os.path.join(SERVICE_ROOT, storage_path)

    # 2. propose one pending edit per image/metadata detection — no pixel work yet
    #    the user can skip any of these before confirming
    #
    # This route can legitimately be called more than once for the same draft
    # (e.g. a slow scan makes the client's request time out and retry while
    # the server is still finishing — see fetchWithRetry in the frontend) so
    # it has to be idempotent: re-propose must reuse an edit that already
    # matches a detection's region rather than creating a second one, or a
    # retried call silently doubles every edit (harmless while both copies
    # sit at the same region, but very visible once one of them is dragged
    # to a new spot and the other, hidden one is still applied at confirm).
    existing_resp = requests.get(f"{EDITS_SERVICE_URL}/drafts/{draft_id}/edits")
    if existing_resp.status_code != 200:
        return jsonify({"error": "failed to fetch existing edits"}), 502
    existing_by_key = {}
    for e in existing_resp.json():
        region = e.get("region_affected")
        key = (e["edit_type"], tuple(sorted(region.items())) if region else None)
        existing_by_key.setdefault(key, e)

    proposed = []
    for d in image_detections:
        # Keyed off category, not region presence: metadata findings never
        # carry a region by design (nothing to blur, only strip), but an
        # image finding can also legitimately lack one now (an implausibly
        # large bounding box gets dropped rather than trusted — see
        # vision_scanner.py's MAX_BOX_AREA_FRAC) without that meaning
        # "strip metadata".
        edit_type = "metadata_strip" if d.get("category") == "metadata" else "blur"
        region = d.get("bounding_region")
        key = (edit_type, tuple(sorted(region.items())) if region else None)

        existing = existing_by_key.get(key)
        if existing:
            proposed.append(existing)
            continue

        payload = {"draft_id": draft_id, "edit_type": edit_type, "region_affected": region}
        edit_resp = requests.post(f"{EDITS_SERVICE_URL}/edits", json=payload)
        if edit_resp.status_code != 201:
            return jsonify({"error": "failed to create edit"}), 502
        created = edit_resp.json()
        proposed.append(created)
        existing_by_key[key] = created

    # 3. for text leaks, generate a redacted caption the user can copy-paste
    # straight over their original — no manual editing required
    text_redaction = None
    if text_detections:
        original_caption = draft.get("text_content") or ""
        suggested_caption = redact_caption(original_caption, text_detections)
        text_redaction = {
            "original_caption": original_caption,
            "suggested_caption": suggested_caption,
            "findings": [
                {
                    "detection_id": d["detection_id"],
                    "category": d["category"],
                    "detail": d.get("detail"),
                } for d in text_detections
            ],
        }

    if not proposed and not text_redaction:
        return jsonify({"error": "nothing to remediate"}), 400

    return jsonify({
        "draft_id": draft_id,
        "original": f"/{original_path}" if original_path else None,
        "proposed_edits": proposed,
        "text_redaction": text_redaction,
    }), 200


@remediate_bp.route("/drafts/<draft_id>/remediate/confirm", methods=["POST"])
def confirm_remediation(draft_id):
    resp = requests.get(f"{EDITS_SERVICE_URL}/drafts/{draft_id}/edits")
    if resp.status_code != 200:
        return jsonify({"error": "failed to fetch edits"}), 502
    # only apply edits the user hasn't skipped
    pending = [e for e in resp.json() if e["status"] == "pending"]
    if not pending:
        return jsonify({"error": "no pending edits to confirm"}), 400

    confirmed = []
    for e in pending:
        patch_resp = requests.patch(
            f"{EDITS_SERVICE_URL}/edits/{e['edit_id']}",
            json={"status": "applied"},
        )
        if patch_resp.status_code != 200:
            return jsonify({"error": "failed to update edit"}), 502
        confirmed.append(patch_resp.json())

    # rebuild from the original using every currently-applied edit, not just
    # the ones confirmed this call, so repeated confirm/revert/restore cycles
    # always produce a file consistent with the edits' current state
    _, error = _regenerate_output(draft_id)
    if error:
        return error

    return jsonify({
        "draft_id": draft_id,
        "confirmed": confirmed,
        "download_url": f"/drafts/{draft_id}/download",
    }), 200


@remediate_bp.route("/drafts/<draft_id>/download", methods=["GET"])
def download_remediated(draft_id):
    # only serve the clean file if the user confirmed (>=1 applied edit)
    resp = requests.get(f"{EDITS_SERVICE_URL}/drafts/{draft_id}/edits")
    if resp.status_code != 200:
        return jsonify({"error": "failed to fetch edits"}), 502
    if not any(e["status"] == "applied" for e in resp.json()):
        return jsonify({"error": "no confirmed remediation for this draft"}), 400

    original_path, error = _get_original_path(draft_id)
    if error:
        return error

    filename = os.path.basename(original_path)
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(path):
        return jsonify({"error": "remediated file not found"}), 404

    return send_file(path, as_attachment=True, download_name=f"trace_clean_{filename}")


@remediate_bp.route("/edits/<edit_id>/revert", methods=["POST"])
def revert_edit(edit_id):
    resp = requests.get(f"{EDITS_SERVICE_URL}/edits/{edit_id}")
    if resp.status_code == 404:
        return jsonify({"error": "edit not found"}), 404
    if resp.status_code != 200:
        return jsonify({"error": "failed to fetch edit"}), 502
    edit = resp.json()
    was_applied = edit["status"] == "applied"

    patch_resp = requests.patch(f"{EDITS_SERVICE_URL}/edits/{edit_id}", json={"status": "reverted"})
    if patch_resp.status_code != 200:
        return jsonify({"error": "failed to revert edit"}), 502

    # only the pixel-baked ("applied") edits affect the served file — undoing
    # a still-pending (not yet confirmed) edit has nothing to regenerate
    if was_applied:
        _, error = _regenerate_output(edit["draft_id"])
        if error:
            return error

    return jsonify(patch_resp.json()), 200


@remediate_bp.route("/edits/<edit_id>/restore", methods=["POST"])
def restore_edit(edit_id):
    """Un-skip a previously reverted edit, putting it back in the pending pool.
    It re-enters the output file on the next /remediate/confirm call, mirroring
    how a freshly-proposed edit is applied — restore does not immediately
    re-bake it in."""
    resp = requests.get(f"{EDITS_SERVICE_URL}/edits/{edit_id}")
    if resp.status_code == 404:
        return jsonify({"error": "edit not found"}), 404
    if resp.status_code != 200:
        return jsonify({"error": "failed to fetch edit"}), 502
    if resp.json()["status"] != "reverted":
        return jsonify({"error": "only reverted edits can be restored"}), 400
    patch_resp = requests.patch(f"{EDITS_SERVICE_URL}/edits/{edit_id}", json={"status": "pending"})
    if patch_resp.status_code != 200:
        return jsonify({"error": "failed to restore edit"}), 502
    return jsonify(patch_resp.json()), 200


# In professional setups, a Load Balancer and/or caller pings this /health URL every few seconds.
# If your code gets stuck in an infinite loop during a request,
# it will stop responding to /health.
@remediate_bp.get("/health")
def health():
    return jsonify({"status": "ok"}), 200
