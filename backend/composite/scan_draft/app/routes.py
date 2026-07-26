import os
import tempfile
import threading
import requests
from flask import Blueprint, request, jsonify

from trace_auth import forwarded_auth_headers
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
SCAN_VIDEO_SERVICE_URL = os.environ.get("SCAN_VIDEO_SERVICE_URL", "http://SCAN_VIDEO:5016")

# Serializes the "scan if nothing's there yet" check per draft_id — mirrors
# remediate_content's _draft_propose_lock, which guards the analogous race
# there. Without this, a slow scan (real OCR/vision/LLM calls easily exceed
# the frontend's retry timeout) lets a retried /process request see "no
# detections yet" and run a second full scan concurrently with the first,
# writing a duplicate set of findings for the same image.
_scan_locks = {}
_scan_locks_guard = threading.Lock()


def _draft_scan_lock(draft_id):
    with _scan_locks_guard:
        return _scan_locks.setdefault(draft_id, threading.Lock())


def _fetch_original_to_tempfile(draft_id, storage_path):
    """Downloads the original file's bytes from upload_post into a local temp
    file. upload_post is the only service that ever writes this file to local
    disk — under Docker Compose all three services shared one volume, but as
    separate Render services they have separate filesystems, so the bytes
    have to cross the network instead of being read off a shared path.
    Returns None if upload_post doesn't have the file (caller treats that the
    same as "nothing to scan")."""
    resp = requests.get(
        f"{UPLOAD_POST_SERVICE_URL}/drafts/{draft_id}/original", headers=forwarded_auth_headers(request)
    )
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
    auth_headers = forwarded_auth_headers(request)
    draft_resp = requests.get(f"{CONTENT_DRAFTS_SERVICE_URL}/drafts/{draft_id}", headers=auth_headers)
    if draft_resp.status_code == 404:
        return None, (jsonify({"error": "draft not found"}), 404)
    if draft_resp.status_code != 200:
        return None, (jsonify({"error": "failed to fetch draft"}), 502)
    draft = draft_resp.json()

    content_type = draft["content_type"]
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
    elif content_type == "video":
        # The video file itself (faces, on-screen text) is scanned by the
        # dedicated scan_video service, not here — Video Intelligence runs
        # as an async job that can take minutes on a real clip, far longer
        # than this request should block for, and scan_video writes its own
        # findings straight to the detections service once done. This call
        # just makes sure that job exists (or nudges it one step forward if
        # it's already running); process_draft is what actually waits for it
        # to finish before deciding how to route the draft.
        video_resp = requests.post(
            f"{SCAN_VIDEO_SERVICE_URL}/drafts/{draft_id}/scan", headers=auth_headers
        )
        if video_resp.status_code not in (200, 201, 202):
            return None, (jsonify({"error": "failed to start video scan"}), 502)

    # A caption can accompany either a text-only post or an image/video post —
    # scan it whenever it's present, not just when content_type is "text".
    findings += scan_text(draft.get("text_content"))

    created = []
    for finding in findings:
        d_resp = requests.post(
            f"{DETECTIONS_SERVICE_URL}/detections",
            json={"draft_id": draft_id, **finding},
            headers=auth_headers,
        )
        if d_resp.status_code != 201:
            return None, (jsonify({"error": "failed to record detection"}), 502)
        created.append(d_resp.json())
    return created, None


@bp.route("/drafts/<draft_id>/scan", methods=["POST"])
def scan_draft_endpoint(draft_id):
    """Run every scanner against a draft and record what they find.
    Runs the caption LLM scan and, for images, EXIF/GPS extraction plus the
    OCR and vision (LLM) scanners — each scanner call can be slow, so this
    endpoint may take several seconds to respond. Always re-scans, even if
    detections already exist for this draft; POST /drafts/{draft_id}/process
    is the endpoint that scans only if nothing's there yet.
    For a video draft, this only scans its caption synchronously and starts
    (or nudges forward) the video file's own scan in scan_video, which runs
    as a separate async job — poll POST /drafts/{draft_id}/process to learn
    when that job finishes and see its findings alongside the caption's.
    ---
    tags:
      - Scan Draft
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: draft_id
        type: string
        required: true
    responses:
      201:
        description: Scan finished; detections (if any) were recorded.
        schema:
          type: object
          properties:
            draft_id:
              type: string
            detections:
              type: array
              items:
                type: object
                properties:
                  detection_id:
                    type: string
                  draft_id:
                    type: string
                  owner_id:
                    type: string
                  resolution:
                    type: string
                    enum: [accepted, rejected]
                    description: Null until a human reviews the detection.
                  category:
                    type: string
                    enum: [face, location, document, metadata, contact, financial]
                  source_type:
                    type: string
                    enum: [text, image, video]
                  exposure_score:
                    type: integer
                    description: 1 (low risk) to 5 (high risk).
                  confidence:
                    type: number
                    format: float
                  model_version:
                    type: string
                  detail:
                    type: string
                  bounding_region:
                    type: object
                    description: Pixel region to blur, as {x, y, w, h}. Null for text/metadata findings with nothing to localize.
                    properties:
                      x:
                        type: integer
                      y:
                        type: integer
                      w:
                        type: integer
                      h:
                        type: integer
                  created_at:
                    type: string
                    format: date-time
                  time_range:
                    type: object
                    description: '{"start":3.2,"end":7.8} seconds. Video findings only — null otherwise.'
      404:
        description: No draft with that id exists.
      502:
        description: Failed to fetch the draft from content_drafts, failed to start/advance the video scan (content_type "video"), or failed to record a detection with the detections service.
    """
    created, error = run_scan(draft_id)
    if error:
        return error
    return jsonify({"draft_id": draft_id, "detections": created}), 201


@bp.route("/drafts/<draft_id>/process", methods=["POST"])
def process_draft(draft_id):
    """Scan a draft if needed, then route it to quarantine or auto-remediation.
    Scans the draft only if it has no detections yet, reusing the results of
    an earlier scan otherwise — this is the endpoint callers should hit after
    upload rather than calling /scan directly. A first-time call on an
    unscanned draft pays the same LLM/vision scan cost as
    POST /drafts/{draft_id}/scan and can take several seconds. Any detection
    at exposure_score >= 4 holds the whole draft for human review
    (quarantine); otherwise every detection is routed to automatic
    remediation.
    For a video draft, the video file itself is scanned asynchronously by
    scan_video and can take much longer than one request — this endpoint
    nudges that job forward on every call but returns a "scanning" outcome
    (202) instead of routing until it actually finishes. Callers should poll
    this same endpoint until they get a 200/201 outcome instead.
    ---
    tags:
      - Scan Draft
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: draft_id
        type: string
        required: true
    responses:
      200:
        description: Either nothing was detected ("clear") or every detection was auto-remediated ("remediated").
        schema:
          type: object
          properties:
            draft_id:
              type: string
            outcome:
              type: string
              enum: [clear, remediated]
            message:
              type: string
              description: Present only for the "clear" outcome.
            remediation:
              type: object
              description: Present only for the "remediated" outcome. The remediation result, as returned by the remediate_content service.
      201:
        description: A detection at exposure_score >= 4 was found; the draft was put on hold for human review.
        schema:
          type: object
          properties:
            draft_id:
              type: string
            outcome:
              type: string
              enum: [quarantined]
            quarantine:
              type: object
              description: The created quarantine hold, as returned by the quarantine_high_risk service.
      202:
        description: The draft's content_type is "video" and its scan is still in progress.
        schema:
          type: object
          properties:
            draft_id:
              type: string
            outcome:
              type: string
              example: scanning
            status:
              type: string
              enum: [running, failed]
      404:
        description: No draft with that id exists.
      502:
        description: A downstream call failed — fetching detections/draft, starting/advancing the video scan, recording a detection, creating the quarantine hold, or applying remediation. See the response body's error/detail for which.
    """
    auth_headers = forwarded_auth_headers(request)
    # The check-then-scan below has to happen under a per-draft lock: two
    # concurrent calls (e.g. a client retry firing while the first, slow
    # scan is still running) could otherwise both see "no detections yet"
    # and both run a full scan, duplicating every finding.
    with _draft_scan_lock(draft_id):
        # fetch detections once; routing decision is based on the worst score present
        resp = requests.get(f"{DETECTIONS_SERVICE_URL}/drafts/{draft_id}/detections", headers=auth_headers)
        if resp.status_code != 200:
            return jsonify({"error": "failed to fetch detections"}), 502
        detections = resp.json()

        if not detections:
            # not scanned yet this call — scan once, then continue with the result
            detections, error = run_scan(draft_id)
            if error:
                return error

    # Video's on-screen content is scanned by scan_video as an async job, so
    # a video draft can have SOME detections already (e.g. from its caption)
    # while the video file itself is still mid-scan. Routing has to wait for
    # that job to actually finish — deciding "clear" or "remediate" from a
    # partial detection set could wave a dangerous video through while its
    # scan is still running.
    draft_resp = requests.get(f"{CONTENT_DRAFTS_SERVICE_URL}/drafts/{draft_id}", headers=auth_headers)
    if draft_resp.status_code == 404:
        return jsonify({"error": "draft not found"}), 404
    if draft_resp.status_code != 200:
        return jsonify({"error": "failed to fetch draft"}), 502
    draft = draft_resp.json()

    if draft["content_type"] == "video" and draft.get("scan_status") != "done":
        # Nudges the job forward (starts it if it hasn't, polls it one step
        # if it has) so repeated client polling of this same endpoint makes
        # progress, rather than just re-checking a status that would
        # otherwise never change on its own.
        video_resp = requests.post(
            f"{SCAN_VIDEO_SERVICE_URL}/drafts/{draft_id}/scan", headers=auth_headers
        )
        if video_resp.status_code not in (200, 201, 202):
            return jsonify({"error": "failed to advance video scan"}), 502
        video_status = video_resp.json().get("status")
        if video_status != "done":
            return jsonify({"draft_id": draft_id, "outcome": "scanning", "status": video_status}), 202
        # finished on this call — route using the now-complete detection set
        detections = video_resp.json().get("detections", [])

    if not detections:
        return jsonify({
            "draft_id": draft_id,
            "outcome": "clear",
            "message": "no sensitive content detected",
        }), 200

    # any region at score >=4 puts the whole draft on hold for human review
    if any(d["exposure_score"] >= 4 for d in detections):
        q_resp = requests.post(
            f"{QUARANTINE_HIGH_RISK_SERVICE_URL}/drafts/{draft_id}/quarantine",
            headers=auth_headers,
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
        f"{REMEDIATE_CONTENT_SERVICE_URL}/drafts/{draft_id}/remediate",
        headers=auth_headers,
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
    """Liveness check.
    Unauthenticated — polled frequently by the container orchestrator, so it must respond even while dependent services are unreachable.
    ---
    tags:
      - Health
    responses:
      200:
        description: The service process is alive.
    """
    return jsonify({"status": "ok"}), 200
