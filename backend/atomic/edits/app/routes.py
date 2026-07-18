from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
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
    """Create an edit.
    Records a proposed edit (blur or metadata strip) for a draft. owner_id is taken from the authenticated caller, not the request body.
    ---
    tags:
      - Edits
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
            - edit_type
          properties:
            draft_id:
              type: string
            edit_type:
              type: string
              enum: [blur, metadata_strip]
            detection_id:
              type: string
              description: Links back to the Detection this edit was proposed for. Omit for a strip with no single detection.
            region_affected:
              type: object
              description: Required-shape region for blur edits ({x, y, w, h}); omit/null for metadata strips.
              properties:
                x:
                  type: number
                y:
                  type: number
                w:
                  type: number
                h:
                  type: number
    responses:
      201:
        description: Edit created.
        schema:
          id: Edit
          type: object
          properties:
            edit_id:
              type: string
            draft_id:
              type: string
            owner_id:
              type: string
            detection_id:
              type: string
            edit_type:
              type: string
            region_affected:
              type: object
            status:
              type: string
            created_at:
              type: string
              format: date-time
      400:
        description: Request body is not a JSON object, a required field is missing, or edit_type is invalid.
    """
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
        owner_id=get_jwt_identity(),
        detection_id=data.get("detection_id"),
        edit_type=data["edit_type"],
        region_affected=data.get("region_affected"),  # null for strips
    )
    db.session.add(edit)
    db.session.commit()
    return jsonify(edit.to_dict()), 201


@edits_bp.route("/drafts/<draft_id>/edits", methods=["GET"])
def list_edits(draft_id):
    """List all edits for a draft.
    Scoped to edits owned by the authenticated caller — edits owned by other users are never returned, even if the draft itself belongs to someone else.
    ---
    tags:
      - Edits
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: draft_id
        type: string
        required: true
    responses:
      200:
        description: The draft's edits owned by the authenticated user.
        schema:
          type: array
          items:
            $ref: "#/definitions/Edit"
    """
    stmt = db.select(Edit).filter_by(draft_id=draft_id, owner_id=get_jwt_identity())
    edits = db.session.scalars(stmt).all()

    return jsonify([e.to_dict() for e in edits]), 200


@edits_bp.route("/edits/<edit_id>", methods=["GET"])
def get_edit(edit_id):
    """Get an edit by id.
    ---
    tags:
      - Edits
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: edit_id
        type: string
        required: true
    responses:
      200:
        description: The edit.
        schema:
          $ref: "#/definitions/Edit"
      403:
        description: The edit belongs to a different user.
      404:
        description: No edit with that id exists.
    """
    edit = db.session.get(Edit, edit_id)
    if edit is None:
        return jsonify({"error": "edit not found"}), 404
    if edit.owner_id != get_jwt_identity():
        return jsonify({"error": "forbidden"}), 403
    return jsonify(edit.to_dict()), 200


@edits_bp.route("/edits/<edit_id>", methods=["PATCH"])
def update_edit(edit_id):
    """Update an edit's status and/or affected region.
    At least one of status or region_affected must be provided. status must be one of pending/applied/reverted; region_affected must be an {x, y, w, h} object.
    ---
    tags:
      - Edits
    security:
      - BearerAuth: []
    consumes:
      - application/json
    parameters:
      - in: path
        name: edit_id
        type: string
        required: true
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            status:
              type: string
              enum: [pending, applied, reverted]
            region_affected:
              type: object
              properties:
                x:
                  type: number
                y:
                  type: number
                w:
                  type: number
                h:
                  type: number
    responses:
      200:
        description: The updated edit.
        schema:
          $ref: "#/definitions/Edit"
      400:
        description: Request body is not a JSON object, neither status nor region_affected was provided, status is invalid, or region_affected is malformed.
      403:
        description: The edit belongs to a different user.
      404:
        description: No edit with that id exists.
    """
    edit = db.session.get(Edit, edit_id)
    if edit is None:
        return jsonify({"error": "edit not found"}), 404
    if edit.owner_id != get_jwt_identity():
        return jsonify({"error": "forbidden"}), 403
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
    """Delete an edit.
    ---
    tags:
      - Edits
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: edit_id
        type: string
        required: true
    responses:
      204:
        description: Edit deleted.
      403:
        description: The edit belongs to a different user.
      404:
        description: No edit with that id exists.
    """
    edit = db.session.get(Edit, edit_id)
    if edit is None:
        return jsonify({"error": "edit not found"}), 404
    if edit.owner_id != get_jwt_identity():
        return jsonify({"error": "forbidden"}), 403
    db.session.delete(edit)
    db.session.commit()
    return "", 204


# Bulk variant for cascading a whole draft's deletion (manage_history's
# selective delete and retention sweep).
@edits_bp.route("/drafts/<draft_id>/edits", methods=["DELETE"])
def delete_edits_for_draft(draft_id):
    """Delete all edits for a draft owned by the caller.
    Bulk variant used to cascade a whole draft's deletion (manage_history's selective delete and retention sweep). Only edits owned by the authenticated user are deleted, even if the draft belongs to someone else.
    ---
    tags:
      - Edits
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: draft_id
        type: string
        required: true
    responses:
      204:
        description: Matching edits deleted (no-op if there were none).
    """
    stmt = db.select(Edit).filter_by(draft_id=draft_id, owner_id=get_jwt_identity())
    edits = db.session.scalars(stmt).all()
    for edit in edits:
        db.session.delete(edit)
    db.session.commit()
    return "", 204

# In professional setups, a Load Balancer and/or caller pings this /health URL every few seconds.
# If your code gets stuck in an infinite loop during a request,
# it will stop responding to /health.
@edits_bp.get("/health")
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
