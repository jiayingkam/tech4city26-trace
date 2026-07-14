import os
import requests
from flask import Blueprint, jsonify, send_file
from PIL import Image, ImageFilter

remediate_bp = Blueprint("remediate_content", __name__)

CONTENT_DRAFTS_SERVICE_URL = os.environ.get("CONTENT_DRAFTS_SERVICE_URL", "http://CONTENT_DRAFTS:5002")
DETECTIONS_SERVICE_URL = os.environ.get("DETECTIONS_SERVICE_URL", "http://DETECTIONS:5003")
EDITS_SERVICE_URL = os.environ.get("EDITS_SERVICE_URL", "http://EDITS:5004")

# Anchored to an absolute path rather than left relative — relative paths
# resolve against the process's current working directory, which turned out
# not to be reliably consistent between requests under the dev server.
SERVICE_ROOT = os.environ.get("SERVICE_ROOT", "/service")
OUTPUT_DIR = os.path.join(SERVICE_ROOT, "storage", "remediated")


def _get_original_path(draft_id):
    """Looks up the draft's real stored file instead of assuming a .jpg extension."""
    resp = requests.get(f"{CONTENT_DRAFTS_SERVICE_URL}/drafts/{draft_id}")
    if resp.status_code == 404:
        return None, (jsonify({"error": "draft not found"}), 404)
    if resp.status_code != 200:
        return None, (jsonify({"error": "failed to fetch draft"}), 502)
    storage_path = resp.json().get("storage_path")
    if not storage_path:
        return None, (jsonify({"error": "draft has no stored file"}), 400)
    return os.path.join(SERVICE_ROOT, storage_path), None


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
    # 1. fetch detections, low/medium risk only (>=4 is quarantine's job)
    resp = requests.get(f"{DETECTIONS_SERVICE_URL}/drafts/{draft_id}/detections")
    if resp.status_code != 200:
        return jsonify({"error": "failed to fetch detections"}), 502
    detections = [d for d in resp.json() if d["exposure_score"] <= 3]
    if not detections:
        return jsonify({"error": "nothing to remediate"}), 400

    # text leaks (phone numbers, addresses, birthdates in a caption) need the
    # user to edit their caption, not an image blur/strip — pulled out here
    # instead of falling through to "no bounding_region -> metadata_strip",
    # which would create a bogus image edit for a detection with no image.
    text_detections = [d for d in detections if d.get("source_type") == "text"]
    image_detections = [d for d in detections if d.get("source_type") != "text"]

    # only look up the stored file if there's actually image work to do —
    # a text-only draft has no storage_path and shouldn't need one
    original_path = None
    if image_detections:
        original_path, error = _get_original_path(draft_id)
        if error:
            return error

    # 2. propose one pending edit per image/metadata detection — no pixel work yet
    #    the user can skip any of these before confirming
    proposed = []
    for d in image_detections:
        payload = {
            "draft_id": draft_id,
            "edit_type": "blur" if d.get("bounding_region") else "metadata_strip",
            "region_affected": d.get("bounding_region"),
        }
        edit_resp = requests.post(f"{EDITS_SERVICE_URL}/edits", json=payload)
        if edit_resp.status_code != 201:
            return jsonify({"error": "failed to create edit"}), 502
        proposed.append(edit_resp.json())

    if not proposed and not text_detections:
        return jsonify({"error": "nothing to remediate"}), 400

    return jsonify({
        "draft_id": draft_id,
        "original": f"/{original_path}" if original_path else None,
        "proposed_edits": proposed,
        # no automated fix exists for these yet — surfaced so the caller can
        # prompt the user to edit their caption text directly
        "needs_text_redaction": [
            {
                "detection_id": d["detection_id"],
                "category": d["category"],
                "detail": d.get("detail"),
            } for d in text_detections
        ],
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
