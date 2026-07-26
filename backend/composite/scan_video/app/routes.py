import os
import threading
import requests
from flask import Blueprint, request, jsonify

from trace_auth import forwarded_auth_headers
import trace_storage
from .scanners.video_scanner import start_video_scan, poll_video_scan, collect_findings

bp = Blueprint("scan_video", __name__)

CONTENT_DRAFTS_SERVICE_URL = os.environ.get("CONTENT_DRAFTS_SERVICE_URL", "http://CONTENT_DRAFTS:5002")
DETECTIONS_SERVICE_URL = os.environ.get("DETECTIONS_SERVICE_URL", "http://DETECTIONS:5003")

# Serializes state-machine advances per draft_id. Without this, two
# concurrent calls (scan_draft nudging the job forward while the frontend is
# also polling directly) could both see "running" flip to "done" at the same
# instant and both write a duplicate set of findings — mirrors scan_draft's
# own _scan_locks, guarding the analogous race there.
_scan_locks = {}
_scan_locks_guard = threading.Lock()


def _draft_scan_lock(draft_id):
    with _scan_locks_guard:
        return _scan_locks.setdefault(draft_id, threading.Lock())


def _get_draft(draft_id, auth_headers):
    resp = requests.get(f"{CONTENT_DRAFTS_SERVICE_URL}/drafts/{draft_id}", headers=auth_headers)
    if resp.status_code == 404:
        return None, (jsonify({"error": "draft not found"}), 404)
    if resp.status_code != 200:
        return None, (jsonify({"error": "failed to fetch draft"}), 502)
    return resp.json(), None


def _patch_draft(draft_id, fields, auth_headers):
    # Best-effort by design would hide a job whose status never got recorded
    # — but an unhandled failure here would also leave the caller unable to
    # tell was recorded, so callers only ever call this right before
    # returning a response built from the same fields they just sent.
    requests.patch(f"{CONTENT_DRAFTS_SERVICE_URL}/drafts/{draft_id}", json=fields, headers=auth_headers)


def _draft_detections(draft_id, auth_headers):
    resp = requests.get(f"{DETECTIONS_SERVICE_URL}/drafts/{draft_id}/detections", headers=auth_headers)
    return resp.json() if resp.status_code == 200 else []


@bp.route("/drafts/<draft_id>/scan", methods=["POST"])
def scan_video_endpoint(draft_id):
    """Start or advance a video draft's async scan.
    Idempotent and safe to call repeatedly — each call moves the draft's scan_status one step forward (null -> running -> done/failed) and reports where it currently stands, so both scan_draft (to kick a video scan off) and a frontend poll loop (to check progress) call this exact same endpoint. A single call never blocks for the whole scan: starting the job returns immediately with "running", and each later call either finds the job still running or, once Video Intelligence finishes, parses its findings, writes them to the detections service, and returns "done". Once "done" or "failed", repeat calls are cheap no-ops that just report the stored outcome.
    ---
    tags:
      - Scan Video
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: draft_id
        type: string
        required: true
    responses:
      200:
        description: The scan had already reached a terminal state (done or failed) on an earlier call.
        schema:
          type: object
          properties:
            draft_id:
              type: string
            status:
              type: string
              enum: [done, failed]
            detections:
              type: array
              description: Present only when status is "done".
              items:
                type: object
      201:
        description: The scan finished on this call; its findings were just recorded.
        schema:
          type: object
          properties:
            draft_id:
              type: string
            status:
              type: string
              example: done
            detections:
              type: array
              items:
                type: object
      202:
        description: The job was just started, or was already running and is still not done.
        schema:
          type: object
          properties:
            draft_id:
              type: string
            status:
              type: string
              example: running
      400:
        description: The draft's content_type is not "video", or it has no stored file.
      404:
        description: No draft with that id exists.
      502:
        description: Failed to fetch/update the draft, failed to record a detection, or the Video Intelligence job itself failed (see the response body's error).
    """
    auth_headers = forwarded_auth_headers(request)
    draft, error = _get_draft(draft_id, auth_headers)
    if error:
        return error
    if draft["content_type"] != "video":
        return jsonify({"error": "draft content_type is not video"}), 400
    if not draft.get("storage_path"):
        return jsonify({"error": "draft has no stored file"}), 400

    with _draft_scan_lock(draft_id):
        # Re-fetch inside the lock: another request may have advanced this
        # draft's scan_status between the check above and acquiring the lock.
        draft, error = _get_draft(draft_id, auth_headers)
        if error:
            return error
        status = draft.get("scan_status")

        if status == "done":
            return jsonify({
                "draft_id": draft_id, "status": "done",
                "detections": _draft_detections(draft_id, auth_headers),
            }), 200

        if status == "failed":
            return jsonify({"draft_id": draft_id, "status": "failed"}), 200

        if status == "running":
            try:
                done, response = poll_video_scan(draft["scan_operation"])
            except Exception as e:
                _patch_draft(draft_id, {"scan_status": "failed", "scan_operation": None}, auth_headers)
                return jsonify({"draft_id": draft_id, "status": "failed", "error": str(e)}), 502
            if not done:
                return jsonify({"draft_id": draft_id, "status": "running"}), 202

            for finding in collect_findings(response):
                d_resp = requests.post(
                    f"{DETECTIONS_SERVICE_URL}/detections",
                    json={"draft_id": draft_id, **finding},
                    headers=auth_headers,
                )
                if d_resp.status_code != 201:
                    return jsonify({"error": "failed to record detection"}), 502

            _patch_draft(draft_id, {"scan_status": "done", "scan_operation": None}, auth_headers)
            return jsonify({
                "draft_id": draft_id, "status": "done",
                "detections": _draft_detections(draft_id, auth_headers),
            }), 201

        # scan_status is null — job hasn't started yet
        input_uri = trace_storage.gcs_uri(draft["storage_path"])
        try:
            operation_name = start_video_scan(input_uri)
        except Exception as e:
            _patch_draft(draft_id, {"scan_status": "failed"}, auth_headers)
            return jsonify({"draft_id": draft_id, "status": "failed", "error": str(e)}), 502
        _patch_draft(draft_id, {"scan_status": "running", "scan_operation": operation_name}, auth_headers)
        return jsonify({"draft_id": draft_id, "status": "running"}), 202


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
