import hashlib
import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone

import requests
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity
from trace_auth import forwarded_auth_headers

bp = Blueprint("update_exposure_profile", __name__)

DETECT_MOSAIC_RISK_URL = os.environ.get(
    "DETECT_MOSAIC_RISK_SERVICE_URL", "http://detect_mosaic_risk:5008"
)
EXPOSURE_PROFILES_URL = os.environ.get(
    "EXPOSURE_PROFILES_SERVICE_URL", "http://exposure_profiles:5005"
)
CONTENT_DRAFTS_SERVICE_URL = os.environ.get(
    "CONTENT_DRAFTS_SERVICE_URL", "http://content_drafts:5002"
)
DETECTIONS_SERVICE_URL = os.environ.get(
    "DETECTIONS_SERVICE_URL", "http://detections:5003"
)
CATEGORIES = ("face", "location", "document", "metadata", "contact", "financial")
MAX_WEEKLY_FINDINGS = 5

# Serializes "recompute + store" per user_id — this service runs a single
# gunicorn worker (threads only), so an in-process lock is sufficient. Without
# it, a double-tapped Refresh or two open tabs can run two rebuilds
# concurrently: both compute independently (each paying for a fresh caption
# LLM call on a cold cache) and both PUT their own profile, so the score the
# user sees is whichever response returned first while the one actually
# stored is whichever write landed last — the two can disagree.
_rebuild_locks = {}
_rebuild_locks_guard = threading.Lock()


def _user_rebuild_lock(user_id):
    with _rebuild_locks_guard:
        return _rebuild_locks.setdefault(user_id, threading.Lock())


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


def _sanitize_finding_detail(detail):
    if not detail:
        return None
    cleaned = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[email hidden]", str(detail))
    cleaned = re.sub(r"\b(?:\+?\d[\d\s().-]{5,}\d)\b", "[number hidden]", cleaned)
    cleaned = " ".join(cleaned.split())
    return cleaned[:117] + "..." if len(cleaned) > 120 else cleaned


def _weekly_finding_from_detection(detection):
    detail = _sanitize_finding_detail(detection.get("detail"))
    finding = {
        "category": detection.get("category"),
        "source_type": detection.get("source_type"),
        "exposure_score": int(detection.get("exposure_score", 0) or 0),
    }
    if detail:
        finding["detail"] = detail
    return finding


def _fetch_user_detections(user_id, headers):
    drafts_resp = requests.get(
        f"{CONTENT_DRAFTS_SERVICE_URL}/users/{user_id}/drafts",
        headers=headers,
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
            headers=headers,
        )
        if detections_resp.status_code != 200:
            return None, (jsonify({"error": "failed to fetch detections"}), 502)
        detections.extend(detections_resp.json())

    return detections, None


def _build_weekly_digest_profile(detections, window_start, window_end):
    breakdown = {category: 0 for category in CATEGORIES}
    risk_points = 0
    findings = []

    for detection in detections:
        created_at = _parse_created_at(detection)
        if created_at is None or not (window_start <= created_at < window_end):
            continue
        category = detection.get("category")
        if category not in breakdown:
            continue
        breakdown[category] += 1
        risk_points += int(detection.get("exposure_score", 0) or 0)
        findings.append(_weekly_finding_from_detection(detection))

    findings.sort(key=lambda item: item.get("exposure_score", 0), reverse=True)

    return {
        "window_start": _iso(window_start),
        "window_end": _iso(window_end),
        "total_flags": sum(breakdown.values()),
        "category_breakdown": breakdown,
        "privacy_health_score": max(0, 100 - min(100, risk_points * 5)),
        "specific_findings": findings[:MAX_WEEKLY_FINDINGS],
    }


def _read_stored_profile(user_id, headers):
    resp = requests.get(f"{EXPOSURE_PROFILES_URL}/users/{user_id}/profile", headers=headers)
    if resp.status_code == 404:
        return {}
    if resp.status_code != 200:
        return None
    return resp.json().get("profile") or {}


def _store_merged_profile(user_id, profile, headers):
    return requests.put(
        f"{EXPOSURE_PROFILES_URL}/users/{user_id}/profile",
        json={"profile": profile},
        headers=headers,
    )


def _stranger_basis_fingerprint(profile):
    """Hashes everything the stranger narrative is derived from (the trajectory,
    excluding any previously-attached stranger block itself). Identical trajectory
    data always yields the same fingerprint, regardless of key order."""
    basis = {k: v for k, v in profile.items() if k not in ("stranger", "stranger_fingerprint")}
    encoded = json.dumps(basis, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


def _compute_profile(user_id, headers):
    """Compute the full mosaic footprint live via detect_mosaic_risk, merging the
    trajectory and the stranger-profile into one blob. Returns None if the core
    trajectory call fails; a missing stranger-profile degrades to an empty one.

    The stranger narrative (synthesise_stranger_view) is an LLM call with no
    caching of its own, so calling it unconditionally on every rebuild made the
    inference wording and confidence tags reroll on every Refresh even when
    nothing about the user's posts had changed. Reused here from the previously
    stored profile whenever the trajectory it's derived from is unchanged —
    identified by a fingerprint over everything BUT the stranger block itself,
    so this can't accidentally compare a stranger block against its own hash.
    """
    traj = requests.get(
        f"{DETECT_MOSAIC_RISK_URL}/users/{user_id}/mosaic-trajectory", headers=headers
    )
    if traj.status_code != 200:
        return None
    profile = traj.json()
    fingerprint = _stranger_basis_fingerprint(profile)

    # Best-effort: any failure reading the previous profile just falls through
    # to regenerating the narrative, same degrade-open behaviour as the caption
    # observation cache in detect_mosaic_risk.
    try:
        previous = _read_stored_profile(user_id, headers)
    except requests.RequestException:
        previous = None

    if previous and previous.get("stranger_fingerprint") == fingerprint and "stranger" in previous:
        profile["stranger"] = previous["stranger"]
    else:
        stranger = requests.get(
            f"{DETECT_MOSAIC_RISK_URL}/users/{user_id}/stranger-profile", headers=headers
        )
        profile["stranger"] = (
            stranger.json() if stranger.status_code == 200
            else {"inferences": [], "overall_confidence": 0}
        )

    profile["stranger_fingerprint"] = fingerprint
    return profile


def _store_profile(user_id, profile, headers):
    return requests.put(
        f"{EXPOSURE_PROFILES_URL}/users/{user_id}/profile",
        json={"profile": profile},
        headers=headers,
    )


def _rebuild_and_store(user_id, headers):
    """Compute + persist, serialized per user_id (see _user_rebuild_lock).
    Returns (response_json, status_code).

    A second caller that queues up behind the lock isn't wasted work: by the
    time it acquires the lock, the first caller has already stored a fresh
    profile, so _compute_profile's fingerprint check (see above) finds a
    match and reuses the stranger block it just wrote instead of re-calling
    the LLM.
    """
    with _user_rebuild_lock(user_id):
        profile = _compute_profile(user_id, headers)
        if profile is None:
            return {"error": "failed to compute profile"}, 502
        store = _store_profile(user_id, profile, headers)
        if store.status_code != 200:
            return {"error": "failed to store profile"}, 502
        return store.json(), 200


@bp.post("/exposure-profiles/update")
def update_digest_profile():
    """Compute the caller's trailing-seven-day digest aggregate and store it.
    This preserves the main branch's materialized mosaic profile while adding a
    weekly_digest aggregate section for the on-demand email flow.
    ---
    tags:
      - Update Exposure Profile
    security:
      - BearerAuth: []
    responses:
      200:
        description: Stored profile with weekly_digest updated.
      400:
        description: Request body or datetime window is invalid.
      502:
        description: Failed to fetch or store downstream data.
    """
    user_id = get_jwt_identity()
    window_start, window_end, error = _window_from_request()
    if error:
        return error

    headers = forwarded_auth_headers(request)
    detections, error = _fetch_user_detections(user_id, headers)
    if error:
        return error

    stored_profile = _read_stored_profile(user_id, headers)
    if stored_profile is None:
        return jsonify({"error": "failed to fetch stored profile"}), 502

    weekly_digest = _build_weekly_digest_profile(detections, window_start, window_end)
    stored_profile["weekly_digest"] = weekly_digest
    store = _store_merged_profile(user_id, stored_profile, headers)
    if store.status_code != 200:
        return jsonify({"error": "failed to store profile"}), 502
    return jsonify(store.json()), 200


@bp.post("/users/<user_id>/rebuild")
def rebuild(user_id):
    """Recompute a user's exposure profile from scratch and store it.
    Called on the write path whenever the user's post history changes (a post is
    published, cancelled, or deleted). Orchestrates detect_mosaic_risk (compute)
    and exposure_profiles (store).
    ---
    tags:
      - Update Exposure Profile
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: user_id
        type: string
        required: true
    responses:
      200:
        description: The freshly computed and stored profile.
      502:
        description: Failed to compute or store the profile.
    """
    body, status = _rebuild_and_store(user_id, forwarded_auth_headers(request))
    return jsonify(body), status


@bp.get("/users/<user_id>/profile")
def get_profile(user_id):
    """Read a user's stored exposure profile, rebuilding it on a cache miss.
    The read path for the frontend — returns the materialized profile instantly
    when present, and self-heals by rebuilding once if none exists yet.
    ---
    tags:
      - Update Exposure Profile
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: user_id
        type: string
        required: true
    responses:
      200:
        description: The stored (or freshly rebuilt) profile.
      403:
        description: user_id does not match the authenticated user.
      502:
        description: Failed to compute or store the profile on a cache miss.
    """
    headers = forwarded_auth_headers(request)
    resp = requests.get(
        f"{EXPOSURE_PROFILES_URL}/users/{user_id}/profile", headers=headers
    )
    if resp.status_code == 200:
        return jsonify(resp.json()), 200
    if resp.status_code == 404:
        body, status = _rebuild_and_store(user_id, headers)
        return jsonify(body), status
    # Forward other upstream statuses as-is (e.g. 403 forbidden).
    try:
        return jsonify(resp.json()), resp.status_code
    except ValueError:
        return jsonify({"error": "upstream error"}), resp.status_code


@bp.delete("/users/<user_id>/profile")
def invalidate_profile(user_id):
    """Invalidate a user's stored profile so the next read rebuilds it.
    The write-path entry point — remediation and history-deletion call this after
    the user's post set changes. Fast (no compute); the rebuild happens lazily on
    the next read. Idempotent.
    ---
    tags:
      - Update Exposure Profile
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: user_id
        type: string
        required: true
    responses:
      204:
        description: Stored profile invalidated (no-op if none existed).
      502:
        description: Failed to reach the storage service.
    """
    resp = requests.delete(
        f"{EXPOSURE_PROFILES_URL}/users/{user_id}/profile",
        headers=forwarded_auth_headers(request),
    )
    if resp.status_code not in (204, 404):
        return jsonify({"error": "failed to invalidate profile"}), 502
    return "", 204


@bp.get("/health")
def health():
    """Liveness check.
    ---
    tags:
      - Health
    responses:
      200:
        description: The service process is alive.
    """
    return jsonify({"status": "ok"}), 200
