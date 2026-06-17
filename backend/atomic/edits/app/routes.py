from flask import Blueprint, request, jsonify
from .db import db
from .models import Edit

edits_bp = Blueprint("edits", __name__)

@edits_bp.route("/edits", methods=["POST"])
def create_edit():
    data = request.get_json()
    edit = Edit(
        draft_id=data["draft_id"],
        edit_type=data["edit_type"],
        region_affected=data.get("region_affected"),  # null for strips
    )
    db.session.add(edit)
    db.session.commit()
    return jsonify(edit.to_dict()), 201


@edits_bp.route("/drafts/<draft_id>/edits", methods=["GET"])
def list_edits(draft_id):
    stmt = db.select(Edit).filter_by(draft_id=draft_id)
    edits = db.session.scalars(stmt).all()
    
    return jsonify([e.to_dict() for e in edits]), 200


@edits_bp.route("/edits/<edit_id>", methods=["GET"])
def get_edit(edit_id):
    edit = db.session.get(Edit, edit_id)
    if edit is None:
        return jsonify({"error": "edit not found"}), 404
    return jsonify(edit.to_dict()), 200


@edits_bp.route("/edits/<edit_id>", methods=["PATCH"])
def update_edit(edit_id):
    edit = db.session.get(Edit, edit_id)
    if edit is None:
        return jsonify({"error": "edit not found"}), 404
    data = request.get_json()
    new_status = data.get("status")
    if new_status not in ("pending", "applied", "reverted"):
        return jsonify({"error": "invalid status"}), 400
    edit.status = new_status
    db.session.commit()
    return jsonify(edit.to_dict()), 200


@edits_bp.route("/edits/<edit_id>", methods=["DELETE"])
def delete_edit(edit_id):
    edit = db.session.get(Edit, edit_id)
    if edit is None:
        return jsonify({"error": "edit not found"}), 404
    db.session.delete(edit)
    db.session.commit()
    return "", 204

# In professional setups, a Load Balancer and/or caller pings this /health URL every few seconds.
# If your code gets stuck in an infinite loop during a request,
# it will stop responding to /health.
@edits_bp.get("/health")
def health():
    return jsonify({"status": "ok"}), 200
