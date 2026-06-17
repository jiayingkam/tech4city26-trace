from flask import Blueprint, request, jsonify
from .db import db
from .models import Detection

detections_bp = Blueprint("detections", __name__)

# yr functions/routes here
@detections_bp.route("/detections", methods=["POST"])
def create_detection():
    data = request.get_json()
    detection = Detection(
        draft_id=data["draft_id"],
        category=data["category"],
        exposure_score=data["exposure_score"],
        confidence=data.get("confidence"),
        model_version=data.get("model_version"),
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
