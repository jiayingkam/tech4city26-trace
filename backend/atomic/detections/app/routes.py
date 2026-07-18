from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
from .db import db
from .models import Detection

detections_bp = Blueprint("detections", __name__)

VALID_CATEGORIES = ("face", "location", "document", "metadata", "contact", "financial", "credentials")
VALID_SOURCE_TYPES = ("text", "image", "video")
VALID_RESOLUTIONS = ("accepted", "rejected")


def _json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, (jsonify({"error": "request body must be a JSON object"}), 400)
    return data, None


def _missing_required(data, fields):
    missing = [field for field in fields if data.get(field) in (None, "")]
    if missing:
        return jsonify({"error": "missing required field(s)", "fields": missing}), 400
    return None


# yr functions/routes here
@detections_bp.route("/detections", methods=["POST"])
def create_detection():
    """Create a detection.
    Records a flagged piece of PII/exposure found in a content draft by a scanner. owner_id is stamped from the authenticated caller's token, never taken from the request body.
    ---
    tags:
      - Detections
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
          required:
            - draft_id
            - category
            - source_type
            - exposure_score
          properties:
            draft_id:
              type: string
            category:
              type: string
              enum: [face, location, document, metadata, contact, financial, credentials]
            source_type:
              type: string
              enum: [text, image, video]
            exposure_score:
              type: integer
              description: Integer from 1 to 5.
              minimum: 1
              maximum: 5
            confidence:
              type: number
              format: float
              description: 0.0-1.0
            model_version:
              type: string
              example: vlm-0.3
            detail:
              type: string
              description: One-line plain-language explanation.
            bounding_region:
              type: object
              description: '{"x":120,"y":340,"w":80,"h":30}, null for text/metadata detections.'
    responses:
      201:
        description: Detection created.
        schema:
          id: Detection
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
              description: null (pending), "accepted", or "rejected".
            category:
              type: string
            source_type:
              type: string
            exposure_score:
              type: integer
            confidence:
              type: number
              format: float
            model_version:
              type: string
            detail:
              type: string
            bounding_region:
              type: object
            created_at:
              type: string
              format: date-time
      400:
        description: Request body is not a JSON object, a required field is missing, category/source_type is invalid, or exposure_score is not an integer from 1 to 5.
    """
    data, error = _json_body()
    if error:
        return error
    error = _missing_required(data, ("draft_id", "category", "source_type", "exposure_score"))
    if error:
        return error
    if data["category"] not in VALID_CATEGORIES:
        return jsonify({"error": "invalid category"}), 400
    if data["source_type"] not in VALID_SOURCE_TYPES:
        return jsonify({"error": "invalid source_type"}), 400
    if type(data["exposure_score"]) is not int or data["exposure_score"] not in range(1, 6):
        return jsonify({"error": "exposure_score must be an integer from 1 to 5"}), 400
    detection = Detection(
        draft_id=data["draft_id"],
        # Stamped from the caller's own token, same as content_drafts' owner_id
        # — never trusted from the request body.
        owner_id=get_jwt_identity(),
        category=data["category"],
        source_type=data["source_type"],
        exposure_score=data["exposure_score"],
        confidence=data.get("confidence"),
        model_version=data.get("model_version"),
        detail=data.get("detail"),
        bounding_region=data.get("bounding_region"),  # null for text/metadata
    )
    db.session.add(detection)
    db.session.commit()
    return jsonify(detection.to_dict()), 201


@detections_bp.route("/drafts/<draft_id>/detections", methods=["GET"])
def list_detections(draft_id):
    """List all detections for a draft.
    Filtered by both draft_id and the authenticated caller's owner_id — a draft owned by someone else returns an empty list rather than a 403, to avoid leaking whether the draft_id exists.
    ---
    tags:
      - Detections
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: draft_id
        type: string
        required: true
    responses:
      200:
        description: The draft's detections.
        schema:
          type: array
          items:
            $ref: "#/definitions/Detection"
    """
    # Filtering by owner_id too (not just draft_id) rather than fetching then
    # checking: a mismatch here just means "not your draft", which reads the
    # same to the caller as "no detections yet" — nothing to distinguish or
    # leak either way.
    stmt = db.select(Detection).filter_by(draft_id=draft_id, owner_id=get_jwt_identity())
    detections = db.session.scalars(stmt).all()

    return jsonify([d.to_dict() for d in detections]), 200


@detections_bp.route("/detections/<detection_id>", methods=["GET"])
def get_detection(detection_id):
    """Get a detection by id.
    ---
    tags:
      - Detections
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: detection_id
        type: string
        required: true
    responses:
      200:
        description: The detection.
        schema:
          $ref: "#/definitions/Detection"
      403:
        description: The detection belongs to a different user.
      404:
        description: No detection with that id exists.
    """
    detection = db.session.get(Detection, detection_id)
    if detection is None:
        return jsonify({"error": "detection not found"}), 404
    if detection.owner_id != get_jwt_identity():
        return jsonify({"error": "forbidden"}), 403
    return jsonify(detection.to_dict()), 200


@detections_bp.route("/detections/<detection_id>", methods=["PATCH"])
def update_detection(detection_id):
    """Update a detection's detail and/or resolution.
    Only detail and resolution are mutable, and at least one of them must be provided. Setting resolution to null clears it back to "pending" (e.g. restoring a reverted edit).
    ---
    tags:
      - Detections
    security:
      - BearerAuth: []
    consumes:
      - application/json
    parameters:
      - in: path
        name: detection_id
        type: string
        required: true
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            detail:
              type: string
              description: Non-empty string, 255 characters or fewer.
            resolution:
              type: string
              enum: [accepted, rejected]
              description: Set to null to clear back to pending.
    responses:
      200:
        description: The updated detection.
        schema:
          $ref: "#/definitions/Detection"
      400:
        description: Request body is not a JSON object, neither detail nor resolution was provided, detail is empty/too long, or resolution is invalid.
      403:
        description: The detection belongs to a different user.
      404:
        description: No detection with that id exists.
    """
    detection = db.session.get(Detection, detection_id)
    if detection is None:
        return jsonify({"error": "detection not found"}), 404
    if detection.owner_id != get_jwt_identity():
        return jsonify({"error": "forbidden"}), 403
    data, error = _json_body()
    if error:
        return error

    if "detail" not in data and "resolution" not in data:
        return jsonify({"error": "must provide detail and/or resolution"}), 400

    if "detail" in data:
        detail = data["detail"]
        if not isinstance(detail, str) or not detail.strip():
            return jsonify({"error": "detail must be a non-empty string"}), 400
        if len(detail) > 255:
            return jsonify({"error": "detail must be 255 characters or fewer"}), 400
        detection.detail = detail.strip()

    if "resolution" in data:
        resolution = data["resolution"]
        # null clears it back to "pending" — e.g. restoring a reverted edit.
        if resolution is not None and resolution not in VALID_RESOLUTIONS:
            return jsonify({"error": "invalid resolution"}), 400
        detection.resolution = resolution

    db.session.commit()
    return jsonify(detection.to_dict()), 200


@detections_bp.route("/detections/<detection_id>", methods=["DELETE"])
def delete_detection(detection_id):
    """Delete a detection.
    ---
    tags:
      - Detections
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: detection_id
        type: string
        required: true
    responses:
      204:
        description: Detection deleted.
      403:
        description: The detection belongs to a different user.
      404:
        description: No detection with that id exists.
    """
    detection = db.session.get(Detection, detection_id)
    if detection is None:
        return jsonify({"error": "detection not found"}), 404
    if detection.owner_id != get_jwt_identity():
        return jsonify({"error": "forbidden"}), 403
    db.session.delete(detection)
    db.session.commit()
    return "", 204


# Bulk variant for cascading a whole draft's deletion (manage_history's
# selective delete and retention sweep) — avoids N individual DELETE calls
# for a draft with many flagged detections.
@detections_bp.route("/drafts/<draft_id>/detections", methods=["DELETE"])
def delete_detections_for_draft(draft_id):
    """Delete all detections for a draft.
    Bulk variant for cascading a whole draft's deletion (manage_history's selective delete and retention sweep) — avoids N individual DELETE calls for a draft with many flagged detections. Only detections owned by the authenticated caller are deleted.
    ---
    tags:
      - Detections
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: draft_id
        type: string
        required: true
    responses:
      204:
        description: Matching detections deleted (no-op if there were none).
    """
    stmt = db.select(Detection).filter_by(draft_id=draft_id, owner_id=get_jwt_identity())
    detections = db.session.scalars(stmt).all()
    for detection in detections:
        db.session.delete(detection)
    db.session.commit()
    return "", 204

# In professional setups, a Load Balancer and/or caller pings this /health URL every few seconds.
# If your code gets stuck in an infinite loop during a request,
# it will stop responding to /health.
@detections_bp.get("/health")
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
