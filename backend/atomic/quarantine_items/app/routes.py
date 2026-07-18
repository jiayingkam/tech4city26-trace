from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
from datetime import datetime, timezone, timedelta
from .db import db
from .models import QuarantineItem

quarantine_bp = Blueprint("quarantine", __name__)

DEFAULT_COOLDOWN_MINUTES = 15
VALID_STATES = ("held", "accepted", "edited", "deleted")


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

@quarantine_bp.route("/quarantine", methods=["POST"])
def create_quarantine():
    """Create a quarantine item.
    Places a draft on hold for the given reason. owner_id is taken from the authenticated caller, not the request body. cooldown_expiry is computed from cooldown_minutes (default 15) at creation time.
    ---
    tags:
      - Quarantine Items
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
            - reason
          properties:
            draft_id:
              type: string
            reason:
              type: string
              example: Visible house number + GPS location
            cooldown_minutes:
              type: integer
              description: Minutes until cooldown_expiry. Must be a positive integer. Defaults to 15.
    responses:
      201:
        description: Quarantine item created.
        schema:
          id: QuarantineItem
          type: object
          properties:
            quarantine_id:
              type: string
            draft_id:
              type: string
            owner_id:
              type: string
            reason:
              type: string
            cooldown_expiry:
              type: string
              format: date-time
            state:
              type: string
              enum: [held, accepted, edited, deleted]
            created_at:
              type: string
              format: date-time
      400:
        description: Request body is not a JSON object, a required field is missing, or cooldown_minutes is not a positive integer.
    """
    data, error = _json_body()
    if error:
        return error
    error = _missing_required(data, ("draft_id", "reason"))
    if error:
        return error
    minutes = data.get("cooldown_minutes", DEFAULT_COOLDOWN_MINUTES)
    if type(minutes) is not int or minutes <= 0:
        return jsonify({"error": "cooldown_minutes must be a positive integer"}), 400
    item = QuarantineItem(
        draft_id=data["draft_id"],
        owner_id=get_jwt_identity(),
        reason=data["reason"],
        cooldown_expiry=datetime.now(timezone.utc) + timedelta(minutes=minutes),
    )
    db.session.add(item)
    db.session.commit()
    return jsonify(item.to_dict()), 201


@quarantine_bp.route("/drafts/<draft_id>/quarantine", methods=["GET"])
def list_quarantine(draft_id):
    """List quarantine items for a draft.
    Scoped to items owned by the authenticated caller.
    ---
    tags:
      - Quarantine Items
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: draft_id
        type: string
        required: true
    responses:
      200:
        description: The draft's quarantine items owned by the authenticated caller.
        schema:
          type: array
          items:
            $ref: "#/definitions/QuarantineItem"
    """
    # No extra sqlalchemy import needed if you use db.select!
    stmt = db.select(QuarantineItem).filter_by(draft_id=draft_id, owner_id=get_jwt_identity())
    items = db.session.scalars(stmt).all()
    return jsonify([i.to_dict() for i in items]), 200


@quarantine_bp.route("/quarantine/<quarantine_id>", methods=["GET"])
def get_quarantine(quarantine_id):
    """Get a quarantine item by id.
    ---
    tags:
      - Quarantine Items
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: quarantine_id
        type: string
        required: true
    responses:
      200:
        description: The quarantine item.
        schema:
          $ref: "#/definitions/QuarantineItem"
      403:
        description: The quarantine item belongs to a different user.
      404:
        description: No quarantine item with that id exists.
    """
    item = db.session.get(QuarantineItem, quarantine_id)
    if item is None:
        return jsonify({"error": "quarantine item not found"}), 404
    if item.owner_id != get_jwt_identity():
        return jsonify({"error": "forbidden"}), 403
    return jsonify(item.to_dict()), 200


@quarantine_bp.route("/quarantine/<quarantine_id>/cooldown", methods=["GET"])
def cooldown_status(quarantine_id):
    """Get the cooldown status of a quarantine item.
    Reports whether the cooldown_expiry timestamp has passed and how many seconds remain.
    ---
    tags:
      - Quarantine Items
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: quarantine_id
        type: string
        required: true
    responses:
      200:
        description: The item's cooldown status.
        schema:
          id: CooldownStatus
          type: object
          properties:
            quarantine_id:
              type: string
            expired:
              type: boolean
            seconds_remaining:
              type: integer
              description: Seconds until cooldown_expiry, floored at 0.
      403:
        description: The quarantine item belongs to a different user.
      404:
        description: No quarantine item with that id exists.
    """
    item = db.session.get(QuarantineItem, quarantine_id)
    if item is None:
        return jsonify({"error": "quarantine item not found"}), 404
    if item.owner_id != get_jwt_identity():
        return jsonify({"error": "forbidden"}), 403
    now = datetime.now(timezone.utc)
    remaining = (item.cooldown_expiry - now).total_seconds()
    return jsonify({
        "quarantine_id": item.quarantine_id,
        "expired": remaining <= 0,
        "seconds_remaining": max(0, int(remaining)),
    }), 200


@quarantine_bp.route("/quarantine/<quarantine_id>", methods=["PATCH"])
def update_quarantine(quarantine_id):
    """Update a quarantine item's state.
    Only state is mutable — everything else about a quarantine item is fixed at creation.
    ---
    tags:
      - Quarantine Items
    security:
      - BearerAuth: []
    consumes:
      - application/json
    parameters:
      - in: path
        name: quarantine_id
        type: string
        required: true
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - state
          properties:
            state:
              type: string
              enum: [held, accepted, edited, deleted]
    responses:
      200:
        description: The updated quarantine item.
        schema:
          $ref: "#/definitions/QuarantineItem"
      400:
        description: Request body is not a JSON object, or state is missing/invalid.
      403:
        description: The quarantine item belongs to a different user.
      404:
        description: No quarantine item with that id exists.
    """
    item = db.session.get(QuarantineItem, quarantine_id)
    if item is None:
        return jsonify({"error": "quarantine item not found"}), 404
    if item.owner_id != get_jwt_identity():
        return jsonify({"error": "forbidden"}), 403
    data, error = _json_body()
    if error:
        return error
    new_state = data.get("state")
    if new_state not in VALID_STATES:
        return jsonify({"error": "invalid state"}), 400
    item.state = new_state
    db.session.commit()
    return jsonify(item.to_dict()), 200


@quarantine_bp.route("/quarantine/<quarantine_id>", methods=["DELETE"])
def delete_quarantine(quarantine_id):
    """Delete a quarantine item.
    ---
    tags:
      - Quarantine Items
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: quarantine_id
        type: string
        required: true
    responses:
      204:
        description: Quarantine item deleted.
      403:
        description: The quarantine item belongs to a different user.
      404:
        description: No quarantine item with that id exists.
    """
    item = db.session.get(QuarantineItem, quarantine_id)
    if item is None:
        return jsonify({"error": "quarantine item not found"}), 404
    if item.owner_id != get_jwt_identity():
        return jsonify({"error": "forbidden"}), 403
    db.session.delete(item)
    db.session.commit()
    return "", 204


# Bulk variant for cascading a whole draft's deletion (manage_history's
# selective delete and retention sweep).
@quarantine_bp.route("/drafts/<draft_id>/quarantine", methods=["DELETE"])
def delete_quarantine_for_draft(draft_id):
    """Delete all quarantine items for a draft.
    Scoped to items owned by the authenticated caller. Used to cascade a draft's deletion.
    ---
    tags:
      - Quarantine Items
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: draft_id
        type: string
        required: true
    responses:
      204:
        description: Matching quarantine items deleted (zero or more).
    """
    stmt = db.select(QuarantineItem).filter_by(draft_id=draft_id, owner_id=get_jwt_identity())
    items = db.session.scalars(stmt).all()
    for item in items:
        db.session.delete(item)
    db.session.commit()
    return "", 204


# In professional setups, a Load Balancer and/or caller pings this /health URL every few seconds.
# If your code gets stuck in an infinite loop during a request,
# it will stop responding to /health.
@quarantine_bp.get("/health")
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
