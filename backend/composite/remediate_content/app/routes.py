import io
import os
import tempfile
import threading
import requests
from flask import Blueprint, request, jsonify, send_file
from PIL import Image, ImageFilter

from trace_auth import forwarded_auth_headers
import trace_storage
from .text_redaction import redact_caption

remediate_bp = Blueprint("remediate_content", __name__)

CONTENT_DRAFTS_SERVICE_URL = os.environ.get("CONTENT_DRAFTS_SERVICE_URL", "http://CONTENT_DRAFTS:5002")
DETECTIONS_SERVICE_URL = os.environ.get("DETECTIONS_SERVICE_URL", "http://DETECTIONS:5003")
EDITS_SERVICE_URL = os.environ.get("EDITS_SERVICE_URL", "http://EDITS:5004")
UPLOAD_POST_SERVICE_URL = os.environ.get("UPLOAD_POST_SERVICE_URL", "http://UPLOAD_POST:5014")


def _set_detection_resolution(detection_id, resolution, auth_headers):
    """Best-effort — a missing/failed PATCH here shouldn't block the edit
    action itself (the edit's own status is the source of truth for what
    actually got applied to the image; resolution is just a label for the
    history menu built on top of it)."""
    if not detection_id:
        return
    requests.patch(
        f"{DETECTIONS_SERVICE_URL}/detections/{detection_id}",
        json={"resolution": resolution},
        headers=auth_headers,
    )

# Serializes the propose step per draft_id so two overlapping /remediate calls can't both create edits.
_propose_locks = {}
_propose_locks_guard = threading.Lock()


def _draft_propose_lock(draft_id):
    with _propose_locks_guard:
        return _propose_locks.setdefault(draft_id, threading.Lock())

# Anchored to an absolute path rather than left relative — relative paths
# resolve against the process's current working directory, which turned out
# not to be reliably consistent between requests under the dev server.
SERVICE_ROOT = os.environ.get("SERVICE_ROOT", "/service")


def _get_draft(draft_id):
    resp = requests.get(f"{CONTENT_DRAFTS_SERVICE_URL}/drafts/{draft_id}", headers=forwarded_auth_headers(request))
    if resp.status_code == 404:
        return None, (jsonify({"error": "draft not found"}), 404)
    if resp.status_code != 200:
        return None, (jsonify({"error": "failed to fetch draft"}), 502)
    return resp.json(), None


def _get_original_path(draft_id):
    """Downloads the draft's original file from upload_post into a local temp
    file and returns its path. upload_post is the only service that writes
    this file (to a GCS bucket), so the bytes have to cross the network
    instead of being read off a shared path. Re-fetched fresh on every call
    rather than cached, since this runs infrequently (propose / confirm /
    revert / restore / download) and staying stateless avoids any risk of a
    stale or missing temp file between requests."""
    draft, error = _get_draft(draft_id)
    if error:
        return None, error
    storage_path = draft.get("storage_path")
    if not storage_path:
        return None, (jsonify({"error": "draft has no stored file"}), 400)

    resp = requests.get(
        f"{UPLOAD_POST_SERVICE_URL}/drafts/{draft_id}/original", headers=forwarded_auth_headers(request)
    )
    if resp.status_code != 200:
        return None, (jsonify({"error": "original file not found"}), 404)

    filename = os.path.basename(storage_path)
    tmp_path = os.path.join(tempfile.gettempdir(), f"{draft_id}_{filename}")
    with open(tmp_path, "wb") as f:
        f.write(resp.content)
    return tmp_path, None


def apply_remediation(original_path, edits):
    """Blur each region that has a box and upload the result to the GCS
    bucket under a blob name derived from original_path. Returns that blob
    name. Whatever format the original was opened as is preserved on save."""
    img = Image.open(original_path)

    for e in edits:
        region = e.get("region_affected")
        if region:
            box = (region["x"], region["y"],
                   region["x"] + region["w"], region["y"] + region["h"])
            blurred = img.crop(box).filter(ImageFilter.GaussianBlur(radius=15))
            img.paste(blurred, box)

    blob_name = os.path.basename(original_path)
    buf = io.BytesIO()
    img.save(buf, format=img.format)  # not passing exif= strips the GPS/EXIF on save
    trace_storage.upload_bytes(blob_name, buf.getvalue())
    return blob_name


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

    resp = requests.get(f"{EDITS_SERVICE_URL}/drafts/{draft_id}/edits", headers=forwarded_auth_headers(request))
    if resp.status_code != 200:
        return None, (jsonify({"error": "failed to fetch edits"}), 502)
    applied = [e for e in resp.json() if e["status"] == "applied"]

    return apply_remediation(original_path, applied), None


@remediate_bp.route("/drafts/<draft_id>/remediate", methods=["POST"])
def remediate_content(draft_id):
    """Propose remediation for a draft's detections.
    Fetches every unresolved detection for the draft and, for each image/metadata detection, creates (or reuses, if already proposed) a pending edit; for each text-source detection, builds a suggested redacted caption. Idempotent — calling this again for the same draft reuses existing pending edits instead of duplicating them. Nothing is written to the output file yet; call .../remediate/confirm to bake the edits in.
    ---
    tags:
      - Remediation
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: draft_id
        type: string
        required: true
    responses:
      200:
        description: Proposed edits and/or a suggested caption redaction, ready for review.
        schema:
          id: RemediationProposal
          type: object
          properties:
            draft_id:
              type: string
            original:
              type: string
              description: Path to the original file, or null if there were no image detections to remediate.
            proposed_edits:
              type: array
              items:
                id: RemediationEdit
                type: object
                properties:
                  edit_id:
                    type: string
                  draft_id:
                    type: string
                  owner_id:
                    type: string
                  detection_id:
                    type: string
                  edit_type:
                    type: string
                    enum: [blur, metadata_strip]
                  region_affected:
                    type: object
                    description: "{x, y, w, h} for blur edits; null for metadata strips."
                  status:
                    type: string
                    enum: [pending, applied, reverted]
                  created_at:
                    type: string
                    format: date-time
            text_redaction:
              type: object
              description: Present only when the draft has text-source detections; otherwise null.
              properties:
                original_caption:
                  type: string
                suggested_caption:
                  type: string
                findings:
                  type: array
                  items:
                    type: object
                    properties:
                      detection_id:
                        type: string
                      category:
                        type: string
                      detail:
                        type: string
      400:
        description: The draft has no unresolved detections, has image detections but no stored file, or none of its detections could be turned into a proposed edit or caption suggestion.
      404:
        description: No draft with that id exists.
      502:
        description: Failed to fetch detections, fetch the draft, fetch existing edits, or create a new edit.
    """
    # No score filter here: when scan_draft calls this directly, every
    # detection present is already <=3 by construction (it only reaches here
    # when nothing scored >=4). When quarantine_high_risk's "edit" action
    # calls this instead, the detections ARE the >=4 finding(s) that caused
    # the hold in the first place — filtering those out left this route with
    # nothing to do and "edit" permanently broken for quarantined items.
    resp = requests.get(
        f"{DETECTIONS_SERVICE_URL}/drafts/{draft_id}/detections", headers=forwarded_auth_headers(request)
    )
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
    # exists for a given detection rather than creating a second one.
    #
    # Matched by detection_id, not region: region can't be trusted as a
    # stable identity — the user can drag a proposed box to a new spot
    # (updateEditRegion), and matching on the now-changed region would miss
    # the existing edit entirely and silently create a duplicate for the
    # same detection. detection_id is the one thing that never changes.
    auth_headers = forwarded_auth_headers(request)
    with _draft_propose_lock(draft_id):
        existing_resp = requests.get(f"{EDITS_SERVICE_URL}/drafts/{draft_id}/edits", headers=auth_headers)
        if existing_resp.status_code != 200:
            return jsonify({"error": "failed to fetch existing edits"}), 502
        existing_by_detection = {}
        for e in existing_resp.json():
            if e.get("detection_id"):
                existing_by_detection.setdefault(e["detection_id"], e)

        proposed = []
        seen_edit_ids = set()
        for d in image_detections:
            # Keyed off category, not region presence: metadata findings never
            # carry a region by design (nothing to blur, only strip), but an
            # image finding can also legitimately lack one now (an implausibly
            # large bounding box gets dropped rather than trusted — see
            # vision_scanner.py's MAX_BOX_AREA_FRAC) without that meaning
            # "strip metadata".
            edit_type = "metadata_strip" if d.get("category") == "metadata" else "blur"
            region = d.get("bounding_region")

            existing = existing_by_detection.get(d["detection_id"])
            if existing:
                # Two detections can legitimately point at the same edit_id
                # here (e.g. a duplicate-scan race upstream produced two
                # near-identical detections before that was fixed) — only
                # surface each edit once regardless of how many detections
                # map to it, so the response list itself is never a source
                # of duplicate rows in the UI.
                if existing["edit_id"] not in seen_edit_ids:
                    proposed.append(existing)
                    seen_edit_ids.add(existing["edit_id"])
                continue

            payload = {
                "draft_id": draft_id,
                "edit_type": edit_type,
                "region_affected": region,
                "detection_id": d["detection_id"],
            }
            edit_resp = requests.post(f"{EDITS_SERVICE_URL}/edits", json=payload, headers=auth_headers)
            if edit_resp.status_code != 201:
                return jsonify({"error": "failed to create edit"}), 502
            created = edit_resp.json()
            proposed.append(created)
            seen_edit_ids.add(created["edit_id"])
            existing_by_detection[d["detection_id"]] = created

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
    """Apply the draft's proposed edits and regenerate the remediated file.
    Applies every pending edit (status -> applied), marks every skipped (reverted) edit's detection as resolved too, then regenerates the downloadable output from the original using all currently-applied edits.
    ---
    tags:
      - Remediation
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: draft_id
        type: string
        required: true
    responses:
      200:
        description: Edits confirmed and the output file regenerated.
        schema:
          id: RemediationConfirmation
          type: object
          properties:
            draft_id:
              type: string
            confirmed:
              type: array
              items:
                $ref: "#/definitions/RemediationEdit"
            download_url:
              type: string
              example: /drafts/abc123/download
      400:
        description: There were no pending or skipped edits to confirm, or the draft has no stored file.
      404:
        description: No draft with that id exists, or the original file could not be found.
      502:
        description: Failed to fetch or update edits, or failed to fetch the draft.
    """
    auth_headers = forwarded_auth_headers(request)
    resp = requests.get(f"{EDITS_SERVICE_URL}/drafts/{draft_id}/edits", headers=auth_headers)
    if resp.status_code != 200:
        return jsonify({"error": "failed to fetch edits"}), 502
    all_edits = resp.json()
    # only apply edits the user hasn't skipped
    pending = [e for e in all_edits if e["status"] == "pending"]
    # skipped edits still standing at confirm time: the user reviewed the
    # suggestion and chose not to apply it, which is a decision, not an
    # unresolved flag — resolve their detections too, so confirming doesn't
    # leave the post stuck at "pending" in History forever.
    skipped = [e for e in all_edits if e["status"] == "reverted"]
    # edits already applied from a previous confirm that was interrupted before
    # text-detection resolutions were set — allow re-confirming so those
    # unresolved detections get cleaned up and the post leaves "pending".
    already_applied = [e for e in all_edits if e["status"] == "applied"]
    if not pending and not skipped and not already_applied:
        return jsonify({"error": "no pending edits to confirm"}), 400

    confirmed = []
    for e in pending:
        patch_resp = requests.patch(
            f"{EDITS_SERVICE_URL}/edits/{e['edit_id']}",
            json={"status": "applied"},
            headers=auth_headers,
        )
        if patch_resp.status_code != 200:
            return jsonify({"error": "failed to update edit"}), 502
        confirmed_edit = patch_resp.json()
        confirmed.append(confirmed_edit)
        _set_detection_resolution(confirmed_edit.get("detection_id"), "accepted", auth_headers)

    for e in skipped:
        _set_detection_resolution(e.get("detection_id"), "rejected", auth_headers)

    for e in already_applied:
        _set_detection_resolution(e.get("detection_id"), "accepted", auth_headers)

    # Text-source detections never get edit records (they get a caption
    # suggestion instead), so the loop above never touches them — resolve
    # them here so the post doesn't stay "pending" in History forever.
    det_resp = requests.get(
        f"{DETECTIONS_SERVICE_URL}/drafts/{draft_id}/detections", headers=auth_headers
    )
    if det_resp.status_code == 200:
        edit_detection_ids = {e.get("detection_id") for e in all_edits}
        for d in det_resp.json():
            if d.get("detection_id") not in edit_detection_ids:
                _set_detection_resolution(d.get("detection_id"), "accepted", auth_headers)

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


@remediate_bp.route("/drafts/<draft_id>/remediate/cancel", methods=["POST"])
def cancel_remediation(draft_id):
    """Cancel a pending remediation.
    The user decided not to post this after all — confirm's counterpart for a pending (non-quarantined) draft. Nothing was ever baked into an output file (confirm never ran), so there's no file to clean up, just the detections' resolution label: marking every still-unresolved one "rejected" is what moves the post out of "pending" in History.
    ---
    tags:
      - Remediation
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: draft_id
        type: string
        required: true
    responses:
      200:
        description: Every unresolved detection for the draft marked rejected.
        schema:
          type: object
          properties:
            draft_id:
              type: string
            status:
              type: string
              example: rejected
      502:
        description: Failed to fetch detections for the draft.
    """
    auth_headers = forwarded_auth_headers(request)
    resp = requests.get(f"{DETECTIONS_SERVICE_URL}/drafts/{draft_id}/detections", headers=auth_headers)
    if resp.status_code != 200:
        return jsonify({"error": "failed to fetch detections"}), 502
    for d in resp.json():
        if d.get("resolution") is None:
            _set_detection_resolution(d["detection_id"], "rejected", auth_headers)
    return jsonify({"draft_id": draft_id, "status": "rejected"}), 200


@remediate_bp.route("/drafts/<draft_id>/download", methods=["GET"])
def download_remediated(draft_id):
    """Download the remediated (clean) file for a draft.
    Only serves the file once at least one edit has been confirmed (status applied) — nothing has been baked in before that.
    ---
    tags:
      - Remediation
    security:
      - BearerAuth: []
    produces:
      - application/octet-stream
    parameters:
      - in: path
        name: draft_id
        type: string
        required: true
    responses:
      200:
        description: The remediated file, served as an attachment.
        schema:
          type: file
      400:
        description: No edits for this draft have been confirmed yet, or the draft has no stored file.
      404:
        description: No draft with that id exists, the original file could not be found, or the remediated file has not been generated yet.
      502:
        description: Failed to fetch edits for the draft, or failed to fetch the draft.
    """
    # only serve the clean file if the user confirmed (>=1 applied edit)
    resp = requests.get(f"{EDITS_SERVICE_URL}/drafts/{draft_id}/edits", headers=forwarded_auth_headers(request))
    if resp.status_code != 200:
        return jsonify({"error": "failed to fetch edits"}), 502
    if not any(e["status"] == "applied" for e in resp.json()):
        return jsonify({"error": "no confirmed remediation for this draft"}), 400

    original_path, error = _get_original_path(draft_id)
    if error:
        return error

    filename = os.path.basename(original_path)
    data = trace_storage.download_bytes(filename)
    if data is None:
        return jsonify({"error": "remediated file not found"}), 404

    return send_file(io.BytesIO(data), as_attachment=True, download_name=f"trace_clean_{filename}")


@remediate_bp.route("/drafts/<draft_id>/remediated", methods=["DELETE"])
def delete_remediated(draft_id):
    """Delete the remediated (clean) output file for a draft.
    Removes the baked-out clean file for a draft being erased from history (manage_history's selective delete / retention sweep). Ownership is enforced by fetching the draft from content_drafts, same as every other route here. Missing/never-remediated is treated as success — the end state (no file) is what the caller wants either way.
    ---
    tags:
      - Remediation
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: draft_id
        type: string
        required: true
    responses:
      204:
        description: Remediated file deleted (no-op if one was never generated).
      404:
        description: No draft with that id exists.
      502:
        description: Failed to fetch the draft.
    """
    draft, error = _get_draft(draft_id)
    if error:
        return error
    storage_path = draft.get("storage_path")
    if storage_path:
        filename = f"{draft_id}_{os.path.basename(storage_path)}"
        trace_storage.delete_blob(filename)
    return "", 204


@remediate_bp.route("/edits/<edit_id>/revert", methods=["POST"])
def revert_edit(edit_id):
    """Revert (skip) an edit.
    Marks the edit reverted and clears its detection's resolution back to unresolved (skipping a fix isn't the same as dismissing the underlying risk). If the edit had already been applied, regenerates the output file from the original using the remaining applied edits.
    ---
    tags:
      - Remediation
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: edit_id
        type: string
        required: true
    responses:
      200:
        description: The reverted edit.
        schema:
          $ref: "#/definitions/RemediationEdit"
      400:
        description: The edit had been applied and its draft has no stored file.
      404:
        description: No edit with that id exists, or (if the edit had been applied) the original file could not be found.
      502:
        description: Failed to fetch or update the edit, or failed to fetch edits/the draft while regenerating the output.
    """
    auth_headers = forwarded_auth_headers(request)
    resp = requests.get(f"{EDITS_SERVICE_URL}/edits/{edit_id}", headers=auth_headers)
    if resp.status_code == 404:
        return jsonify({"error": "edit not found"}), 404
    if resp.status_code != 200:
        return jsonify({"error": "failed to fetch edit"}), 502
    edit = resp.json()
    was_applied = edit["status"] == "applied"

    patch_resp = requests.patch(
        f"{EDITS_SERVICE_URL}/edits/{edit_id}", json={"status": "reverted"}, headers=auth_headers
    )
    if patch_resp.status_code != 200:
        return jsonify({"error": "failed to revert edit"}), 502
    # Un-resolved, not "rejected" — skipping a fix isn't the same as dismissing
    # the underlying risk as a false positive; it just hasn't been dealt with.
    _set_detection_resolution(edit.get("detection_id"), None, auth_headers)

    # only the pixel-baked ("applied") edits affect the served file — undoing
    # a still-pending (not yet confirmed) edit has nothing to regenerate
    if was_applied:
        _, error = _regenerate_output(edit["draft_id"])
        if error:
            return error

    return jsonify(patch_resp.json()), 200


@remediate_bp.route("/edits/<edit_id>/restore", methods=["POST"])
def restore_edit(edit_id):
    """Restore a previously reverted edit.
    Un-skip a previously reverted edit, putting it back in the pending pool. It re-enters the output file on the next /remediate/confirm call, mirroring how a freshly-proposed edit is applied — restore does not immediately re-bake it in.
    ---
    tags:
      - Remediation
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: edit_id
        type: string
        required: true
    responses:
      200:
        description: The restored (pending) edit.
        schema:
          $ref: "#/definitions/RemediationEdit"
      400:
        description: The edit's status was not reverted.
      404:
        description: No edit with that id exists.
      502:
        description: Failed to fetch or update the edit.
    """
    auth_headers = forwarded_auth_headers(request)
    resp = requests.get(f"{EDITS_SERVICE_URL}/edits/{edit_id}", headers=auth_headers)
    if resp.status_code == 404:
        return jsonify({"error": "edit not found"}), 404
    if resp.status_code != 200:
        return jsonify({"error": "failed to fetch edit"}), 502
    if resp.json()["status"] != "reverted":
        return jsonify({"error": "only reverted edits can be restored"}), 400
    patch_resp = requests.patch(
        f"{EDITS_SERVICE_URL}/edits/{edit_id}", json={"status": "pending"}, headers=auth_headers
    )
    if patch_resp.status_code != 200:
        return jsonify({"error": "failed to restore edit"}), 502
    return jsonify(patch_resp.json()), 200


# In professional setups, a Load Balancer and/or caller pings this /health URL every few seconds.
# If your code gets stuck in an infinite loop during a request,
# it will stop responding to /health.
@remediate_bp.get("/health")
def health():
    """Liveness check.
    Unauthenticated — polled frequently by the container orchestrator, so it must respond even while downstream services are unreachable.
    ---
    tags:
      - Health
    responses:
      200:
        description: The service process is alive.
    """
    return jsonify({"status": "ok"}), 200
