import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import requests
from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity

from trace_auth import forwarded_auth_headers

bp = Blueprint("manage_history", __name__)

# Must comfortably exceed db_retry.wait_for_db's own budget (12 retries *
# 10s = up to ~120s for Azure SQL serverless to resume from auto-pause) —
# otherwise a downstream service that's still waking its DB looks
# indistinguishable from one that's actually down, and this service fails a
# request it could have just waited out.
DOWNSTREAM_TIMEOUT_S = 130

CONTENT_DRAFTS_SERVICE_URL = os.environ.get("CONTENT_DRAFTS_SERVICE_URL", "http://CONTENT_DRAFTS:5002")
DETECTIONS_SERVICE_URL = os.environ.get("DETECTIONS_SERVICE_URL", "http://DETECTIONS:5003")
EDITS_SERVICE_URL = os.environ.get("EDITS_SERVICE_URL", "http://EDITS:5004")
QUARANTINE_ITEMS_SERVICE_URL = os.environ.get("QUARANTINE_ITEMS_SERVICE_URL", "http://QUARANTINE_ITEMS:5006")
UPLOAD_POST_SERVICE_URL = os.environ.get("UPLOAD_POST_SERVICE_URL", "http://UPLOAD_POST:5014")
REMEDIATE_CONTENT_SERVICE_URL = os.environ.get("REMEDIATE_CONTENT_SERVICE_URL", "http://REMEDIATE_CONTENT:5011")
USERS_SERVICE_URL = os.environ.get("USERS_SERVICE_URL", "http://USERS:5001")

INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY")
RETENTION_WINDOW_DAYS = 90  # "3 months", anchored per-draft to captured_at

VALID_FILTERS = ("all", "accepted", "rejected", "quarantined", "pending")

CATEGORY_LABELS = {
    "face": "a face",
    "location": "a location detail",
    "document": "an identifying document",
    "financial": "a financial detail",
    "contact": "a contact detail",
    "credentials": "a password or access code",
    "metadata": "hidden location metadata",
}


def _list_drafts(owner_id, auth_headers):
    resp = requests.get(
        f"{CONTENT_DRAFTS_SERVICE_URL}/users/{owner_id}/drafts", headers=auth_headers, timeout=DOWNSTREAM_TIMEOUT_S
    )
    if resp.status_code != 200:
        return None
    return resp.json()


def _summarize_flags(detections):
    """A short, plain-language stand-in for an AI-generated summary — no
    summarization model is wired up, so this just names what was found."""
    categories = []
    for d in detections:
        label = CATEGORY_LABELS.get(d["category"], d["category"])
        if label not in categories:
            categories.append(label)
    if not categories:
        return "No sensitive content detected."
    return "Flagged: " + ", ".join(categories) + "."


def _derive_status(detections, quarantine_items):
    """One overall outcome per post, in priority order:
    1. Currently held in quarantine, cooldown still running -> "quarantined".
    2. Anything still unresolved (no explicit accept/reject yet) -> "pending".
    3. Anything rejected (fixed/withheld) takes priority over accepted, since
       catching and correcting an exposure is the more important signal to
       surface than the things left as-is alongside it.
    4. Otherwise, if it was released from quarantine or every flag was
       accepted as-is -> "accepted".
    5. No flags at all -> "accepted" (nothing to resolve)."""
    held = next((q for q in quarantine_items if q["state"] == "held"), None)
    if held:
        return "quarantined", held

    if any(d.get("resolution") is None for d in detections):
        return "pending", None
    if any(d.get("resolution") == "rejected" for d in detections):
        return "rejected", None
    if any(q["state"] == "deleted" for q in quarantine_items):
        return "rejected", None
    return "accepted", None


def _post_summary(draft, detections, quarantine_items):
    status, held_item = _derive_status(detections, quarantine_items)
    summary = {
        "draft_id": draft["draft_id"],
        "captured_at": draft["captured_at"],
        "status": status,
        "caption": draft.get("text_content") or None,
        "summary": _summarize_flags(detections),
        "has_image": draft.get("content_type") == "image" and bool(draft.get("storage_path")),
    }
    if held_item:
        summary["cooldown_expiry"] = held_item["cooldown_expiry"]
        summary["quarantine_id"] = held_item["quarantine_id"]
        # Needed by the frontend's "continue this quarantined post" screen,
        # which reuses the same plain-language hold reason the compose flow
        # shows right after scanning.
        summary["reason"] = held_item.get("reason")
    return summary


def _fetch_detections(draft_id, auth_headers):
    resp = requests.get(
        f"{DETECTIONS_SERVICE_URL}/drafts/{draft_id}/detections", headers=auth_headers, timeout=DOWNSTREAM_TIMEOUT_S
    )
    return resp.json() if resp.status_code == 200 else []


def _fetch_quarantine_items(draft_id, auth_headers):
    resp = requests.get(
        f"{QUARANTINE_ITEMS_SERVICE_URL}/drafts/{draft_id}/quarantine",
        headers=auth_headers,
        timeout=DOWNSTREAM_TIMEOUT_S,
    )
    return resp.json() if resp.status_code == 200 else []


@bp.route("/history", methods=["GET"])
def get_history():
    """Get the caller's post history.
    One card per post for the History screen, fanned out across every draft the caller owns (content_drafts' owner-scoped list is the only cross-draft index that already exists) — no single atomic service can answer "all of a user's posts with their outcome" itself.
    ---
    tags:
      - History
    security:
      - BearerAuth: []
    parameters:
      - in: query
        name: filter
        type: string
        enum: [all, accepted, rejected, quarantined, pending]
        required: false
        description: Restrict to posts with this derived status. Defaults to "all".
    responses:
      200:
        description: The caller's posts, most recently captured first.
        schema:
          type: array
          items:
            type: object
            properties:
              draft_id:
                type: string
              captured_at:
                type: string
                format: date-time
              status:
                type: string
                enum: [accepted, rejected, quarantined, pending]
              caption:
                type: string
                description: The draft's text_content, if any.
              summary:
                type: string
                description: Plain-language list of what was flagged, or "No sensitive content detected."
              has_image:
                type: boolean
              cooldown_expiry:
                type: string
                format: date-time
                description: Present only when status is "quarantined".
              quarantine_id:
                type: string
                description: Present only when status is "quarantined".
              reason:
                type: string
                description: Plain-language hold reason. Present only when status is "quarantined".
      400:
        description: filter is not one of the supported values.
      502:
        description: Failed to fetch the caller's drafts from the content drafts service.
    """
    status_filter = request.args.get("filter", "all")
    if status_filter not in VALID_FILTERS:
        return jsonify({"error": "invalid filter"}), 400
    auth_headers = forwarded_auth_headers(request)

    try:
        drafts = _list_drafts(get_jwt_identity(), auth_headers)
        if drafts is None:
            return jsonify({"error": "failed to fetch drafts"}), 502

        # Per-draft detections/quarantine lookups are independent of each other,
        # so fan them all out at once instead of two round trips per draft in
        # sequence — with enough drafts, the sequential version's wall time
        # stacks up past the frontend's own per-request timeout (fetchWithRetry).
        with ThreadPoolExecutor(max_workers=max(1, len(drafts) * 2)) as executor:
            det_futures = {
                d["draft_id"]: executor.submit(_fetch_detections, d["draft_id"], auth_headers) for d in drafts
            }
            q_futures = {
                d["draft_id"]: executor.submit(_fetch_quarantine_items, d["draft_id"], auth_headers) for d in drafts
            }
            posts = [
                _post_summary(draft, det_futures[draft["draft_id"]].result(), q_futures[draft["draft_id"]].result())
                for draft in drafts
            ]
    except requests.exceptions.RequestException:
        # A downstream service is still waking its own DB from auto-pause (or
        # is genuinely unreachable) — either way, tell the caller to back off
        # and retry rather than surfacing an unhandled 500.
        return jsonify({"error": "a service is still starting up, please try again shortly"}), 503

    if status_filter != "all":
        posts = [p for p in posts if p["status"] == status_filter]

    posts.sort(key=lambda p: p.get("captured_at") or "", reverse=True)
    return jsonify(posts), 200


def _cascade_delete_draft(draft_id, auth_headers):
    """Deletes everything tied to a draft — its detections, edits,
    quarantine records, the stored files, then the draft row itself.
    Ownership is enforced independently by each of these downstream
    services (all keyed off the same forwarded/impersonated token), not
    re-checked here — a mismatched draft_id just means each of these calls
    404s/403s harmlessly rather than deleting someone else's data."""
    requests.delete(f"{DETECTIONS_SERVICE_URL}/drafts/{draft_id}/detections", headers=auth_headers)
    requests.delete(f"{EDITS_SERVICE_URL}/drafts/{draft_id}/edits", headers=auth_headers)
    requests.delete(f"{QUARANTINE_ITEMS_SERVICE_URL}/drafts/{draft_id}/quarantine", headers=auth_headers)
    requests.delete(f"{UPLOAD_POST_SERVICE_URL}/drafts/{draft_id}/original", headers=auth_headers)
    requests.delete(f"{REMEDIATE_CONTENT_SERVICE_URL}/drafts/{draft_id}/remediated", headers=auth_headers)
    requests.delete(f"{CONTENT_DRAFTS_SERVICE_URL}/drafts/{draft_id}", headers=auth_headers)


@bp.route("/history/delete", methods=["POST"])
def delete_history():
    """Delete a batch of history items.
    Selective delete for the History screen — a mixed batch of whole posts, individual flags, and/or individual quarantine items ('select all' is just the frontend sending every currently-visible id). Each id is attempted independently and its own result reported, rather than the whole batch failing together, since one bad id (someone else's, or already gone) shouldn't block deleting the rest.
    ---
    tags:
      - History
    security:
      - BearerAuth: []
    consumes:
      - application/json
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            draft_ids:
              type: array
              items:
                type: string
              description: Whole posts to cascade-delete (draft + its detections, edits, quarantine records, and stored files).
            detection_ids:
              type: array
              items:
                type: string
              description: Individual flags to delete without touching the rest of their draft.
            quarantine_ids:
              type: array
              items:
                type: string
              description: Individual quarantine holds to delete without touching the rest of their draft.
    responses:
      200:
        description: Per-id outcome for every id that was submitted.
        schema:
          type: object
          properties:
            draft_ids:
              type: object
              description: Keyed by the submitted draft_id. Cascade deletes are always reported as "deleted".
              additionalProperties:
                type: string
                enum: [deleted]
            detection_ids:
              type: object
              description: Keyed by the submitted detection_id.
              additionalProperties:
                type: string
                enum: [deleted, failed]
            quarantine_ids:
              type: object
              description: Keyed by the submitted quarantine_id.
              additionalProperties:
                type: string
                enum: [deleted, failed]
      400:
        description: Request body is not a JSON object, or none of draft_ids, detection_ids, quarantine_ids was provided.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "request body must be a JSON object"}), 400

    auth_headers = forwarded_auth_headers(request)
    draft_ids = data.get("draft_ids") or []
    detection_ids = data.get("detection_ids") or []
    quarantine_ids = data.get("quarantine_ids") or []

    if not (draft_ids or detection_ids or quarantine_ids):
        return jsonify({"error": "must provide draft_ids, detection_ids, and/or quarantine_ids"}), 400

    results = {"draft_ids": {}, "detection_ids": {}, "quarantine_ids": {}}

    for draft_id in draft_ids:
        _cascade_delete_draft(draft_id, auth_headers)
        results["draft_ids"][draft_id] = "deleted"

    for detection_id in detection_ids:
        resp = requests.delete(f"{DETECTIONS_SERVICE_URL}/detections/{detection_id}", headers=auth_headers)
        results["detection_ids"][detection_id] = "deleted" if resp.status_code == 204 else "failed"

    for quarantine_id in quarantine_ids:
        resp = requests.delete(f"{QUARANTINE_ITEMS_SERVICE_URL}/quarantine/{quarantine_id}", headers=auth_headers)
        results["quarantine_ids"][quarantine_id] = "deleted" if resp.status_code == 204 else "failed"

    return jsonify(results), 200


@bp.route("/internal/sweep-expired", methods=["POST"])
def sweep_expired():
    """Sweep expired drafts for retention.
    For every user on auto_expire, cascades any draft older than the retention window (90 days, anchored per-draft to captured_at). Triggered manually for the demo — in production this would be an external Render Cron Job hitting this same endpoint on a schedule. No in-process scheduler here: Render's free tier sleeps idle services, and a multi-worker setup would double-fire an in-process timer — both real risks with nothing here to catch them.

    Has no logged-in user driving it, so it can't forward a caller's token the way every other route in this file does; instead it asks users for a short-lived impersonation token per user (see users' /internal/impersonate) so this still goes through the exact same authenticated/authorized code paths as a real request, just on the sweep's own schedule.
    ---
    tags:
      - Internal
    security:
      - InternalApiKey: []
    responses:
      200:
        description: draft_ids that were swept (cascade-deleted) this run.
        schema:
          type: object
          properties:
            swept_draft_ids:
              type: array
              items:
                type: string
      502:
        description: Failed to fetch the list of auto_expire users from the users service.
    """
    users_resp = requests.get(
        f"{USERS_SERVICE_URL}/internal/users",
        params={"retention_mode": "auto_expire"},
        headers={"X-Internal-Key": INTERNAL_API_KEY},
    )
    if users_resp.status_code != 200:
        return jsonify({"error": "failed to fetch users"}), 502

    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_WINDOW_DAYS)
    swept = []
    for user in users_resp.json():
        impersonate_resp = requests.post(
            f"{USERS_SERVICE_URL}/internal/impersonate",
            json={"user_id": user["user_id"]},
            headers={"X-Internal-Key": INTERNAL_API_KEY},
        )
        if impersonate_resp.status_code != 200:
            continue
        auth_headers = {"Authorization": f"Bearer {impersonate_resp.json()['token']}"}

        drafts = _list_drafts(user["user_id"], auth_headers) or []
        for draft in drafts:
            captured_at = datetime.fromisoformat(draft["captured_at"])
            if captured_at < cutoff:
                _cascade_delete_draft(draft["draft_id"], auth_headers)
                swept.append(draft["draft_id"])

    return jsonify({"swept_draft_ids": swept}), 200


# In professional setups, a Load Balancer and/or caller pings this /health URL every few seconds.
# If your code gets stuck in an infinite loop during a request,
# it will stop responding to /health.
@bp.get("/health")
def health():
    """Liveness check.
    Unauthenticated — polled frequently by the container orchestrator, so it must respond even while dependencies are unreachable.
    ---
    tags:
      - Health
    responses:
      200:
        description: The service process is alive.
    """
    return jsonify({"status": "ok"}), 200
