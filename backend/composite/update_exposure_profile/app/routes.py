import os
from datetime import datetime, timedelta, timezone

import requests
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity
from trace_auth import forwarded_auth_headers

bp = Blueprint("update_exposure_profile", __name__)

DOWNSTREAM_TIMEOUT_S = 130
CONTENT_DRAFTS_SERVICE_URL = os.environ.get("CONTENT_DRAFTS_SERVICE_URL", "http://content_drafts:5002")
DETECTIONS_SERVICE_URL = os.environ.get("DETECTIONS_SERVICE_URL", "http://detections:5003")
EXPOSURE_PROFILES_SERVICE_URL = os.environ.get("EXPOSURE_PROFILES_SERVICE_URL", "http://exposure_profiles:5005")
CATEGORIES = ("face", "location", "document", "metadata", "contact", "financial")


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _as_utc(dt):
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_datetime(value, field):
    if not value:
        return None, None
    try:
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00"))), None
    except ValueError:
        return None, (jsonify({"error": f"{field} must be an ISO datetime"}), 400)


def _window_from_request():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return None, None, (jsonify({"error": "request body must be a JSON object"}), 400)

    window_end, error = _parse_datetime(data.get("window_end"), "window_end")
    if error:
        return None, None, error
    window_start, error = _parse_datetime(data.get("window_start"), "window_start")
    if error:
        return None, None, error

    window_end = window_end or datetime.now(timezone.utc)
    window_start = window_start or (window_end - timedelta(days=7))
    if window_start >= window_end:
        return None, None, (jsonify({"error": "window_start must be before window_end"}), 400)
    return window_start, window_end, None


def _parse_created_at(detection):
    value = detection.get("created_at")
    if not value:
        return None
    try:
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _in_window(detection, window_start, window_end):
    created_at = _parse_created_at(detection)
    return created_at is not None and window_start <= created_at < window_end


def _fetch_user_detections(owner_id, auth_headers):
    drafts_resp = requests.get(
        f"{CONTENT_DRAFTS_SERVICE_URL}/users/{owner_id}/drafts",
        headers=auth_headers,
        timeout=DOWNSTREAM_TIMEOUT_S,
    )
    if drafts_resp.status_code != 200:
        return None, (jsonify({"error": "failed to fetch drafts"}), 502)

    detections = []
    for draft in drafts_resp.json():
        draft_id = draft.get("draft_id")
        if not draft_id:
            continue
        detections_resp = requests.get(
            f"{DETECTIONS_SERVICE_URL}/drafts/{draft_id}/detections",
            headers=auth_headers,
            timeout=DOWNSTREAM_TIMEOUT_S,
        )
        if detections_resp.status_code != 200:
            return None, (jsonify({"error": "failed to fetch detections"}), 502)
        detections.extend(detections_resp.json())

    return detections, None


def _build_exposure_profile(detections, window_start, window_end):
    breakdown = {category: 0 for category in CATEGORIES}
    risk_points = 0

    for detection in detections:
        if not _in_window(detection, window_start, window_end):
            continue
        category = detection.get("category")
        if category not in breakdown:
            continue
        breakdown[category] += 1
        risk_points += int(detection.get("exposure_score", 0) or 0)

    total_flags = sum(breakdown.values())
    privacy_health_score = max(0, 100 - min(100, risk_points * 5))
    return {
        "window_start": _iso(window_start),
        "window_end": _iso(window_end),
        "total_flags": total_flags,
        "category_breakdown": breakdown,
        "privacy_health_score": privacy_health_score,
    }


def _write_exposure_profile(profile, auth_headers):
    resp = requests.post(
        f"{EXPOSURE_PROFILES_SERVICE_URL}/exposure-profiles",
        json=profile,
        headers={**auth_headers, "Content-Type": "application/json"},
        timeout=DOWNSTREAM_TIMEOUT_S,
    )
    if resp.status_code != 201:
        return None, (jsonify({"error": "failed to write exposure profile"}), 502)
    return resp.json(), None


@bp.post("/exposure-profiles/update")
def update_exposure_profile():
    """Aggregate the caller's detections into an exposure profile row.
    Defaults to the trailing seven days, but accepts window_start/window_end
    ISO datetimes for repeatable development and testing.
    ---
    tags:
      - Update Exposure Profile
    security:
      - BearerAuth: []
    consumes:
      - application/json
    responses:
      201:
        description: Exposure profile row created.
      400:
        description: Request body or datetime window is invalid.
      502:
        description: Failed to fetch or write downstream data.
      503:
        description: A downstream service is still starting up.
    """
    owner_id = get_jwt_identity()
    window_start, window_end, error = _window_from_request()
    if error:
        return error

    auth_headers = forwarded_auth_headers(request)
    try:
        detections, error = _fetch_user_detections(owner_id, auth_headers)
        if error:
            return error
        profile = _build_exposure_profile(detections, window_start, window_end)
        created_profile, error = _write_exposure_profile(profile, auth_headers)
        if error:
            return error
    except requests.exceptions.RequestException:
        return jsonify({"error": "a service is still starting up, please try again shortly"}), 503

    return jsonify(created_profile), 201


# In professional setups, a Load Balancer and/or caller pings this /health URL every few seconds.
# If your code gets stuck in an infinite loop during a request,
# it will stop responding to /health.
@bp.get("/health")
def health():
    """Liveness check.
    Unauthenticated — polled frequently by the container orchestrator, so it must respond even while the database is unreachable.
    ---
    tags:
      - Health
    responses:
      200:
        description: The service process is alive.
    """
    return jsonify({"status": "ok"}), 200
