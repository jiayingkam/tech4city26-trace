import json
from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
from .db import db
from .models import ExposureProfile

bp = Blueprint("exposure_profiles", __name__)


@bp.route("/users/<user_id>/profile", methods=["GET"])
def get_profile(user_id):
    """Get a user's stored exposure profile.
    Returns the cached mosaic footprint (trajectory, score, stranger-profile, etc.)
    computed by update_exposure_profile. 404 if one has never been built.
    ---
    tags:
      - Exposure Profiles
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: user_id
        type: string
        required: true
    responses:
      200:
        description: The stored profile.
        schema:
          id: ExposureProfile
          type: object
          properties:
            user_id:
              type: string
            profile:
              type: object
              description: The full computed mosaic blob, or null.
            updated_at:
              type: string
              format: date-time
      403:
        description: user_id does not match the authenticated user.
      404:
        description: No profile has been built for this user yet.
    """
    if user_id != get_jwt_identity():
        return jsonify({"error": "forbidden"}), 403
    profile = db.session.get(ExposureProfile, user_id)
    if profile is None:
        return jsonify({"error": "profile not found"}), 404
    return jsonify(profile.to_dict()), 200


@bp.route("/users/<user_id>/profile", methods=["PUT"])
def put_profile(user_id):
    """Create or replace a user's exposure profile (upsert).
    update_exposure_profile calls this after recomputing the mosaic footprint.
    ---
    tags:
      - Exposure Profiles
    security:
      - BearerAuth: []
    consumes:
      - application/json
    parameters:
      - in: path
        name: user_id
        type: string
        required: true
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - profile
          properties:
            profile:
              type: object
              description: The full computed mosaic blob to store.
    responses:
      200:
        description: The stored profile.
        schema:
          $ref: "#/definitions/ExposureProfile"
      400:
        description: Request body is not a JSON object or is missing 'profile'.
      403:
        description: user_id does not match the authenticated user.
    """
    if user_id != get_jwt_identity():
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or "profile" not in data:
        return jsonify({"error": "request body must be a JSON object with a 'profile' field"}), 400

    profile_text = json.dumps(data["profile"])
    profile = db.session.get(ExposureProfile, user_id)
    if profile is None:
        profile = ExposureProfile(user_id=user_id, profile_json=profile_text)
        db.session.add(profile)
    else:
        profile.profile_json = profile_text
    db.session.commit()
    return jsonify(profile.to_dict()), 200


@bp.route("/users/<user_id>/profile", methods=["DELETE"])
def delete_profile(user_id):
    """Delete a user's stored exposure profile (cache invalidation).
    Called on the write path when the user's post history changes, so the next
    read rebuilds from scratch. Idempotent — deleting a non-existent profile
    is still a success, since the desired end state (no cached profile) holds.
    ---
    tags:
      - Exposure Profiles
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: user_id
        type: string
        required: true
    responses:
      204:
        description: Profile deleted (no-op if none existed).
      403:
        description: user_id does not match the authenticated user.
    """
    if user_id != get_jwt_identity():
        return jsonify({"error": "forbidden"}), 403
    profile = db.session.get(ExposureProfile, user_id)
    if profile is not None:
        db.session.delete(profile)
        db.session.commit()
    return "", 204


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
