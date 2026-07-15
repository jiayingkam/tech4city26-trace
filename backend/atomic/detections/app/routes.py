from flask import Blueprint, request, jsonify
from .db import db
from .models import Detection

detections_bp = Blueprint("detections", __name__)

VALID_CATEGORIES = ("face", "location", "document", "metadata", "contact", "financial", "credentials")
VALID_SOURCE_TYPES = ("text", "image", "video")


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
    stmt = db.select(Detection).filter_by(draft_id=draft_id)
    detections = db.session.scalars(stmt).all()
    
    return jsonify([d.to_dict() for d in detections]), 200


@detections_bp.route("/detections/<detection_id>", methods=["GET"])
def get_detection(detection_id):
    detection = db.session.get(Detection, detection_id)
    if detection is None:
        return jsonify({"error": "detection not found"}), 404
    return jsonify(detection.to_dict()), 200


@detections_bp.route("/detections/<detection_id>", methods=["PATCH"])
def update_detection(detection_id):
    detection = db.session.get(Detection, detection_id)
    if detection is None:
        return jsonify({"error": "detection not found"}), 404
    data, error = _json_body()
    if error:
        return error

    if "detail" not in data:
        return jsonify({"error": "must provide detail"}), 400

    detail = data["detail"]
    if not isinstance(detail, str) or not detail.strip():
        return jsonify({"error": "detail must be a non-empty string"}), 400
    if len(detail) > 255:
        return jsonify({"error": "detail must be 255 characters or fewer"}), 400

    detection.detail = detail.strip()
    db.session.commit()
    return jsonify(detection.to_dict()), 200


@detections_bp.route("/detections/<detection_id>", methods=["DELETE"])
def delete_detection(detection_id):
    detection = db.session.get(Detection, detection_id)
    if detection is None:
        return jsonify({"error": "detection not found"}), 404
    db.session.delete(detection)
    db.session.commit()
    return "", 204

# In professional setups, a Load Balancer and/or caller pings this /health URL every few seconds.
# If your code gets stuck in an infinite loop during a request,
# it will stop responding to /health.
@detections_bp.get("/health")
def health():
    return jsonify({"status": "ok"}), 200
