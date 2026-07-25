from datetime import datetime
from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
from .db import db
from .models import ExposureProfile

bp = Blueprint("exposure_profiles", __name__)

CATEGORIES = ("face", "location", "document", "metadata", "contact", "financial")


def _parse_datetime(value, field):
    if not value:
        return None, (jsonify({"error": f"{field} is required"}), 400)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")), None
    except ValueError:
        return None, (jsonify({"error": f"{field} must be an ISO datetime"}), 400)


def _json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, (jsonify({"error": "request body must be a JSON object"}), 400)
    return data, None


def _category_count(data, category):
    breakdown = data.get("category_breakdown") or {}
    return int(breakdown.get(category, data.get(f"{category}_flags", 0)) or 0)


@bp.get("/users/<owner_id>/exposure-profiles")
def list_exposure_profiles(owner_id):
    """List aggregate exposure profile rows for a user in a time window.
    Filtered by both path owner_id and authenticated identity. Returns only
    category-level aggregate rows, never raw detections or post content.
    ---
    tags:
      - Exposure Profiles
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: owner_id
        type: string
        required: true
      - in: query
        name: window_start
        type: string
        format: date-time
        required: true
      - in: query
        name: window_end
        type: string
        format: date-time
        required: true
    responses:
      200:
        description: Matching aggregate exposure profile rows.
      400:
        description: window_start or window_end is missing or invalid.
      403:
        description: owner_id does not match the authenticated user.
    """
    if owner_id != get_jwt_identity():
        return jsonify({"error": "forbidden"}), 403

    window_start, error = _parse_datetime(request.args.get("window_start"), "window_start")
    if error:
        return error
    window_end, error = _parse_datetime(request.args.get("window_end"), "window_end")
    if error:
        return error
    if window_start >= window_end:
        return jsonify({"error": "window_start must be before window_end"}), 400

    stmt = (
        db.select(ExposureProfile)
        .filter(
            ExposureProfile.owner_id == owner_id,
            ExposureProfile.window_end > window_start,
            ExposureProfile.window_start < window_end,
        )
        .order_by(ExposureProfile.window_start.asc())
    )
    profiles = db.session.scalars(stmt).all()
    return jsonify([p.to_dict() for p in profiles]), 200


@bp.post("/exposure-profiles")
def create_exposure_profile():
    """Create an aggregate exposure profile row.
    Intended for update_exposure_profile to write already-aggregated data.
    owner_id is always stamped from the authenticated caller's token.
    ---
    tags:
      - Exposure Profiles
    security:
      - BearerAuth: []
    consumes:
      - application/json
    responses:
      201:
        description: Created profile row.
      400:
        description: Request body is invalid.
    """
    data, error = _json_body()
    if error:
        return error
    window_start, error = _parse_datetime(data.get("window_start"), "window_start")
    if error:
        return error
    window_end, error = _parse_datetime(data.get("window_end"), "window_end")
    if error:
        return error
    if window_start >= window_end:
        return jsonify({"error": "window_start must be before window_end"}), 400

    profile = ExposureProfile(
        owner_id=get_jwt_identity(),
        window_start=window_start,
        window_end=window_end,
        total_flags=int(data.get("total_flags", 0) or 0),
        face_flags=_category_count(data, "face"),
        location_flags=_category_count(data, "location"),
        document_flags=_category_count(data, "document"),
        metadata_flags=_category_count(data, "metadata"),
        contact_flags=_category_count(data, "contact"),
        financial_flags=_category_count(data, "financial"),
        privacy_health_score=data.get("privacy_health_score"),
    )
    db.session.add(profile)
    db.session.commit()
    return jsonify(profile.to_dict()), 201


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
