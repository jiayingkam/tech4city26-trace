import os
import requests
from flask import Blueprint, jsonify, request
from trace_auth import forwarded_auth_headers

bp = Blueprint("update_exposure_profile", __name__)

DETECT_MOSAIC_RISK_URL = os.environ.get(
    "DETECT_MOSAIC_RISK_SERVICE_URL", "http://detect_mosaic_risk:5008"
)
EXPOSURE_PROFILES_URL = os.environ.get(
    "EXPOSURE_PROFILES_SERVICE_URL", "http://exposure_profiles:5005"
)


def _compute_profile(user_id, headers):
    """Compute the full mosaic footprint live via detect_mosaic_risk, merging the
    trajectory and the stranger-profile into one blob. Returns None if the core
    trajectory call fails; a missing stranger-profile degrades to an empty one."""
    traj = requests.get(
        f"{DETECT_MOSAIC_RISK_URL}/users/{user_id}/mosaic-trajectory", headers=headers
    )
    if traj.status_code != 200:
        return None
    profile = traj.json()

    stranger = requests.get(
        f"{DETECT_MOSAIC_RISK_URL}/users/{user_id}/stranger-profile", headers=headers
    )
    profile["stranger"] = (
        stranger.json() if stranger.status_code == 200
        else {"inferences": [], "overall_confidence": 0}
    )
    return profile


def _store_profile(user_id, profile, headers):
    return requests.put(
        f"{EXPOSURE_PROFILES_URL}/users/{user_id}/profile",
        json={"profile": profile},
        headers=headers,
    )


def _rebuild_and_store(user_id, headers):
    """Compute + persist. Returns (response_json, status_code)."""
    profile = _compute_profile(user_id, headers)
    if profile is None:
        return {"error": "failed to compute profile"}, 502
    store = _store_profile(user_id, profile, headers)
    if store.status_code != 200:
        return {"error": "failed to store profile"}, 502
    return store.json(), 200


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
