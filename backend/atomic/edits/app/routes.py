from flask import Blueprint, request, jsonify
from .db import db
from .models import Edit

edits_bp = Blueprint("edits", __name__)

VALID_EDIT_TYPES = ("blur", "metadata_strip")
VALID_STATUSES = ("pending", "applied", "reverted")


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


def _valid_region(region):
    if not isinstance(region, dict):
        return False
    if set(region.keys()) != {"x", "y", "w", "h"}:
        return False
    return all(isinstance(region[k], (int, float)) for k in ("x", "y", "w", "h"))


@edits_bp.route("/edits", methods=["POST"])
def create_edit():
    data, error = _json_body()
    if error:
        return error
    error = _missing_required(data, ("draft_id", "edit_type"))
    if error:
        return error
    if data["edit_type"] not in VALID_EDIT_TYPES:
        return jsonify({"error": "invalid edit_type"}), 400
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
    data, error = _json_body()
    if error:
        return error

    if "status" not in data and "region_affected" not in data:
        return jsonify({"error": "must provide status and/or region_affected"}), 400

    if "status" in data:
        if data["status"] not in VALID_STATUSES:
            return jsonify({"error": "invalid status"}), 400
        edit.status = data["status"]

    if "region_affected" in data:
        if not _valid_region(data["region_affected"]):
            return jsonify({"error": "invalid region_affected"}), 400
        edit.region_affected = data["region_affected"]

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
