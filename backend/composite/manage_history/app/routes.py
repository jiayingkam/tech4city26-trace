import os
from datetime import datetime, timedelta, timezone
import requests
from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity

from trace_auth import forwarded_auth_headers

bp = Blueprint("manage_history", __name__)

CONTENT_DRAFTS_SERVICE_URL = os.environ.get("CONTENT_DRAFTS_SERVICE_URL", "http://CONTENT_DRAFTS:5002")
DETECTIONS_SERVICE_URL = os.environ.get("DETECTIONS_SERVICE_URL", "http://DETECTIONS:5003")
EDITS_SERVICE_URL = os.environ.get("EDITS_SERVICE_URL", "http://EDITS:5004")
QUARANTINE_ITEMS_SERVICE_URL = os.environ.get("QUARANTINE_ITEMS_SERVICE_URL", "http://QUARANTINE_ITEMS:5006")
UPLOAD_POST_SERVICE_URL = os.environ.get("UPLOAD_POST_SERVICE_URL", "http://UPLOAD_POST:5014")
REMEDIATE_CONTENT_SERVICE_URL = os.environ.get("REMEDIATE_CONTENT_SERVICE_URL", "http://REMEDIATE_CONTENT:5011")
USERS_SERVICE_URL = os.environ.get("USERS_SERVICE_URL", "http://USERS:5001")

INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY")
RETENTION_WINDOW_DAYS = 90  # "3 months", anchored per-draft to captured_at

VALID_FILTERS = ("all", "accepted", "rejected")


def _list_drafts(owner_id, auth_headers):
    resp = requests.get(f"{CONTENT_DRAFTS_SERVICE_URL}/users/{owner_id}/drafts", headers=auth_headers)
    if resp.status_code != 200:
        return None
    return resp.json()


@bp.route("/history", methods=["GET"])
def get_history():
    """All-detections view for the hamburger menu, fanned out across every
    draft the caller owns (content_drafts' owner-scoped list is the only
    cross-draft index that already exists) and merged into one list, since
    no single atomic service can answer "all of a user's detections" itself."""
    resolution_filter = request.args.get("filter", "all")
    if resolution_filter not in VALID_FILTERS:
        return jsonify({"error": "invalid filter"}), 400
    auth_headers = forwarded_auth_headers(request)

    drafts = _list_drafts(get_jwt_identity(), auth_headers)
    if drafts is None:
        return jsonify({"error": "failed to fetch drafts"}), 502

    detections = []
    for draft in drafts:
        resp = requests.get(
            f"{DETECTIONS_SERVICE_URL}/drafts/{draft['draft_id']}/detections", headers=auth_headers
        )
        if resp.status_code == 200:
            detections.extend(resp.json())

    if resolution_filter != "all":
        detections = [d for d in detections if d.get("resolution") == resolution_filter]

    detections.sort(key=lambda d: d.get("created_at") or "", reverse=True)
    return jsonify(detections), 200


@bp.route("/history/quarantine", methods=["GET"])
def get_history_quarantine():
    """Same fan-out as /history, but for quarantine items — the separate
    'Quarantined Items' tab."""
    auth_headers = forwarded_auth_headers(request)

    drafts = _list_drafts(get_jwt_identity(), auth_headers)
    if drafts is None:
        return jsonify({"error": "failed to fetch drafts"}), 502

    items = []
    for draft in drafts:
        resp = requests.get(
            f"{QUARANTINE_ITEMS_SERVICE_URL}/drafts/{draft['draft_id']}/quarantine", headers=auth_headers
        )
        if resp.status_code == 200:
            items.extend(resp.json())

    items.sort(key=lambda i: i.get("created_at") or "", reverse=True)
    return jsonify(items), 200


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
    """Selective delete for the History screen — a mixed batch of whole
    posts, individual flags, and/or individual quarantine items ('select
    all' is just the frontend sending every currently-visible id). Each id
    is attempted independently and its own result reported, rather than the
    whole batch failing together, since one bad id (someone else's, or
    already gone) shouldn't block deleting the rest."""
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
    """Retention sweep: for every user on auto_expire, cascades any draft
    older than the retention window. Triggered manually for the demo — in
    production this would be an external Render Cron Job hitting this same
    endpoint on a schedule. No in-process scheduler here: Render's free tier
    sleeps idle services, and a multi-worker setup would double-fire an
    in-process timer — both real risks with nothing here to catch them.

    Has no logged-in user driving it, so it can't forward a caller's token
    the way every other route in this file does; instead it asks users for
    a short-lived impersonation token per user (see users' /internal/impersonate)
    so this still goes through the exact same authenticated/authorized code
    paths as a real request, just on the sweep's own schedule."""
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
    return jsonify({"status": "ok"}), 200
