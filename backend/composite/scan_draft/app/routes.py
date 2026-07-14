import os
import tempfile
import requests
from flask import Blueprint, jsonify

from .scanners.exif_scanner import scan_metadata
from .scanners.text_scanner import scan_text
from .scanners.vision_scanner import scan_image
from .scanners.ocr_scanner import scan_ocr

bp = Blueprint("scan_draft", __name__)

CONTENT_DRAFTS_SERVICE_URL = os.environ.get("CONTENT_DRAFTS_SERVICE_URL", "http://CONTENT_DRAFTS:5002")
DETECTIONS_SERVICE_URL = os.environ.get("DETECTIONS_SERVICE_URL", "http://DETECTIONS:5003")
QUARANTINE_HIGH_RISK_SERVICE_URL = os.environ.get("QUARANTINE_HIGH_RISK_SERVICE_URL", "http://QUARANTINE_HIGH_RISK:5010")
REMEDIATE_CONTENT_SERVICE_URL = os.environ.get("REMEDIATE_CONTENT_SERVICE_URL", "http://REMEDIATE_CONTENT:5011")
UPLOAD_POST_SERVICE_URL = os.environ.get("UPLOAD_POST_SERVICE_URL", "http://UPLOAD_POST:5014")


def _fetch_original_to_tempfile(draft_id, storage_path):
    """Downloads the original file's bytes from upload_post into a local temp
    file. upload_post is the only service that ever writes this file to local
    disk — under Docker Compose all three services shared one volume, but as
    separate Render services they have separate filesystems, so the bytes
    have to cross the network instead of being read off a shared path.
    Returns None if upload_post doesn't have the file (caller treats that the
    same as "nothing to scan")."""
    resp = requests.get(f"{UPLOAD_POST_SERVICE_URL}/drafts/{draft_id}/original")
    if resp.status_code != 200:
        return None
    suffix = os.path.splitext(storage_path)[1]
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(resp.content)
    return tmp_path


def run_scan(draft_id):
    """Reads the draft from content_drafts, runs the classifier for its content
    type, and writes each finding to detections. Returns (created_detections, None)
    on success or (None, (response, status)) on failure."""
    draft_resp = requests.get(f"{CONTENT_DRAFTS_SERVICE_URL}/drafts/{draft_id}")
    if draft_resp.status_code == 404:
        return None, (jsonify({"error": "draft not found"}), 404)
    if draft_resp.status_code != 200:
        return None, (jsonify({"error": "failed to fetch draft"}), 502)
    draft = draft_resp.json()

    content_type = draft["content_type"]
    if content_type == "video":
        # video scanning isn't built yet — Phase 1 covers text + image only
        return None, (jsonify({"error": "video scanning not yet supported"}), 501)

    findings = []
    if content_type == "image":
        storage_path = draft.get("storage_path")
        local_path = _fetch_original_to_tempfile(draft_id, storage_path) if storage_path else None
        if local_path:
            try:
                findings += scan_metadata(local_path)
                findings += scan_ocr(local_path)
                findings += scan_image(local_path)
            finally:
                os.remove(local_path)

    # A caption can accompany either a text-only post or an image/video post —
    # scan it whenever it's present, not just when content_type is "text".
    findings += scan_text(draft.get("text_content"))

    created = []
    for finding in findings:
        d_resp = requests.post(f"{DETECTIONS_SERVICE_URL}/detections", json={"draft_id": draft_id, **finding})
        if d_resp.status_code != 201:
            return None, (jsonify({"error": "failed to record detection"}), 502)
        created.append(d_resp.json())
    return created, None


@bp.route("/drafts/<draft_id>/scan", methods=["POST"])
def scan_draft_endpoint(draft_id):
    created, error = run_scan(draft_id)
    if error:
        return error
    return jsonify({"draft_id": draft_id, "detections": created}), 201


@bp.route("/drafts/<draft_id>/process", methods=["POST"])
def process_draft(draft_id):
    # fetch detections once; routing decision is based on the worst score present
    resp = requests.get(f"{DETECTIONS_SERVICE_URL}/drafts/{draft_id}/detections")
    if resp.status_code != 200:
        return jsonify({"error": "failed to fetch detections"}), 502
    detections = resp.json()

    if not detections:
        # not scanned yet this call — scan once, then continue with the result
        detections, error = run_scan(draft_id)
        if error:
            return error
        if not detections:
            return jsonify({
                "draft_id": draft_id,
                "outcome": "clear",
                "message": "no sensitive content detected",
            }), 200

    # any region at score >=4 puts the whole draft on hold for human review
    if any(d["exposure_score"] >= 4 for d in detections):
        q_resp = requests.post(
            f"{QUARANTINE_HIGH_RISK_SERVICE_URL}/drafts/{draft_id}/quarantine"
        )
        if q_resp.status_code != 201:
            return jsonify({"error": "quarantine failed", "detail": q_resp.json()}), 502
        return jsonify({
            "draft_id": draft_id,
            "outcome": "quarantined",
            "quarantine": q_resp.json(),
        }), 201

    # all scores <=3 — safe to auto-remediate
    r_resp = requests.post(
        f"{REMEDIATE_CONTENT_SERVICE_URL}/drafts/{draft_id}/remediate"
    )
    if r_resp.status_code != 200:
        return jsonify({"error": "remediation failed", "detail": r_resp.json()}), 502
    return jsonify({
        "draft_id": draft_id,
        "outcome": "remediated",
        "remediation": r_resp.json(),
    }), 200


# In professional setups, a Load Balancer and/or caller pings this /health URL every few seconds.
# If your code gets stuck in an infinite loop during a request,
# it will stop responding to /health.
@bp.get("/health")
def health():
    return jsonify({"status": "ok"}), 200
