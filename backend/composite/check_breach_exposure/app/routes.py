import os
import threading
from datetime import datetime, timezone

import requests
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity
from trace_auth import forwarded_auth_headers

from .leakcheck import check_leakcheck
from .holehe_check import check_holehe

bp = Blueprint("check_breach_exposure", __name__)

USERS_SERVICE_URL = os.environ.get("USERS_SERVICE_URL", "http://users:5001")
EXPOSURE_PROFILES_SERVICE_URL = os.environ.get(
    "EXPOSURE_PROFILES_SERVICE_URL", "http://exposure_profiles:5005"
)

# Serializes "recompute + store" per user_id, same pattern (and same reason)
# as update_exposure_profile's _user_rebuild_lock — without it, a double-tap
# or two open tabs can run two LeakCheck/Holehe passes concurrently for the
# same user, each paying for a fresh Holehe scan and racing on which write
# lands last. Not a cache — every call through this lock still does a real
# check once it gets its turn; it only prevents two concurrent ones.
_check_locks = {}
_check_locks_guard = threading.Lock()


def _user_check_lock(user_id):
    with _check_locks_guard:
        return _check_locks.setdefault(user_id, threading.Lock())


def _get_self(headers):
    resp = requests.get(f"{USERS_SERVICE_URL}/me", headers=headers, timeout=8)
    if resp.status_code != 200:
        return None
    return resp.json()


def _read_stored_profile(user_id, headers):
    resp = requests.get(
        f"{EXPOSURE_PROFILES_SERVICE_URL}/users/{user_id}/profile", headers=headers, timeout=8
    )
    if resp.status_code == 404:
        return {}
    if resp.status_code != 200:
        return None
    return resp.json().get("profile") or {}


def _store_merged_profile(user_id, profile, headers):
    return requests.put(
        f"{EXPOSURE_PROFILES_SERVICE_URL}/users/{user_id}/profile",
        json={"profile": profile},
        headers=headers,
        timeout=8,
    )


def _compute_and_store(user_id, email, headers):
    leakcheck_result = check_leakcheck(email)
    free_block = (
        {"status": "unavailable", "error": "leakcheck check failed or was rate-limited"}
        if leakcheck_result is None
        else {"status": "ok", **leakcheck_result}
    )

    holehe_result = check_holehe(email)
    deep_block = (
        {"status": "unavailable", "error": "deep scan failed or timed out"}
        if holehe_result is None
        else {
            "status": "ok",
            "platforms_attempted": holehe_result["total_attempted"],
            "platforms_conclusive": len(holehe_result["conclusive"]),
            "registered": [d for d in holehe_result["conclusive"] if d["exists"]],
        }
    )

    result = {
        "email": email,
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "leakcheck": free_block,
        "holehe": deep_block,
    }

    # Best-effort persistence: a storage failure doesn't block returning the
    # result the caller is waiting on right now, same degrade-open shape as
    # update_exposure_profile's stranger-cache handling.
    profile = _read_stored_profile(user_id, headers)
    if profile is not None:
        profile["breach_exposure"] = result
        _store_merged_profile(user_id, profile, headers)

    return result


@bp.post("/breach-exposure/check")
def check_exposure():
    """Check the caller's own email against LeakCheck and Holehe.
    Always runs a real check — deliberately not cached. Unlike the mosaic
    exposure profile (where an unchanged post history really does guarantee
    an unchanged output), breach/registration data can change independently
    of anything the caller did, so "the email is the same as last time"
    isn't a valid reason to skip rechecking it; an explicit "Check" click
    should always mean check now. Re-persists into exposure_profiles under
    'breach_exposure' either way. The email is always the caller's own,
    resolved server-side via /me — never a client-supplied field, so this
    can only ever check data the caller has a lawful basis to check
    (themselves).
    ---
    tags:
      - Check Breach Exposure
    security:
      - BearerAuth: []
    responses:
      200:
        description: The freshly computed breach-exposure result.
      502:
        description: Failed to resolve the caller's own account.
    """
    user_id = get_jwt_identity()
    headers = forwarded_auth_headers(request)
    me = _get_self(headers)
    if me is None:
        return jsonify({"error": "failed to resolve caller"}), 502

    email = me["email"]

    with _user_check_lock(user_id):
        result = _compute_and_store(user_id, email, headers)
        return jsonify(result), 200


@bp.get("/breach-exposure/status")
def get_status():
    """Read the caller's stored breach-exposure result without recomputing.
    No external calls — for page-load display of whatever was last computed.
    ---
    tags:
      - Check Breach Exposure
    security:
      - BearerAuth: []
    responses:
      200:
        description: The stored result, or null if never checked.
      502:
        description: Failed to fetch the stored profile.
    """
    user_id = get_jwt_identity()
    headers = forwarded_auth_headers(request)
    profile = _read_stored_profile(user_id, headers)
    if profile is None:
        return jsonify({"error": "failed to fetch profile"}), 502
    return jsonify(profile.get("breach_exposure")), 200


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
