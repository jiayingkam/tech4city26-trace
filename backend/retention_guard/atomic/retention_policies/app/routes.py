from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from .db import db
from .models import RetentionPolicy

retention_policies_bp = Blueprint("retention_policies", __name__)


def _json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, (jsonify({"error": "request body must be a JSON object"}), 400)
    return data, None


def _get_owned_policy(policy_id):
    policy = db.session.get(RetentionPolicy, policy_id)
    if policy is None or policy.owner_id != get_jwt_identity():
        return None, (jsonify({"error": "policy not found"}), 404)
    return policy, None


@retention_policies_bp.route("/policies", methods=["POST"])
@jwt_required()
def create_policy():
    """Create a retention policy.
    data_source_id is stored as given, not verified against data_sources — atomic services don't cross-call each other in this repo (only composites do); enforce_retention validates the source/table/columns for real the first time it actually scans.
    ---
    tags:
      - Retention Policies
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
            - data_source_id
            - table_name
            - inactive_days
          properties:
            data_source_id:
              type: string
            table_name:
              type: string
              example: customers
            inactive_days:
              type: integer
              example: 180
            action:
              type: string
              enum: [anonymise, delete, flag]
              default: anonymise
            enabled:
              type: boolean
              default: true
            schedule_interval_minutes:
              type: integer
              description: Omit or null for manual-only (never auto-scanned).
    responses:
      201:
        description: The created policy.
        schema:
          $ref: "#/definitions/RetentionPolicy"
      400:
        description: Request body is not a JSON object, a required field is missing/invalid, or action is invalid.
    """
    data, error = _json_body()
    if error:
        return error
    data_source_id = data.get("data_source_id")
    table_name = data.get("table_name")
    inactive_days = data.get("inactive_days")
    action = data.get("action", "anonymise")
    if not data_source_id or not table_name or not isinstance(inactive_days, int) or inactive_days <= 0:
        return jsonify({"error": "data_source_id, table_name, and a positive integer inactive_days are required"}), 400
    if action not in RetentionPolicy.VALID_ACTIONS:
        return jsonify({"error": f"action must be one of {RetentionPolicy.VALID_ACTIONS}"}), 400
    schedule_interval_minutes = data.get("schedule_interval_minutes")
    if schedule_interval_minutes is not None and (not isinstance(schedule_interval_minutes, int) or schedule_interval_minutes <= 0):
        return jsonify({"error": "schedule_interval_minutes must be a positive integer or null"}), 400

    policy = RetentionPolicy(
        owner_id=get_jwt_identity(),
        data_source_id=data_source_id,
        table_name=table_name,
        inactive_days=inactive_days,
        action=action,
        enabled=bool(data.get("enabled", True)),
        schedule_interval_minutes=schedule_interval_minutes,
    )
    db.session.add(policy)
    db.session.commit()
    return jsonify(policy.to_dict()), 201


@retention_policies_bp.route("/policies", methods=["GET"])
@jwt_required()
def list_policies():
    """List the caller's retention policies.
    ---
    tags:
      - Retention Policies
    security:
      - BearerAuth: []
    parameters:
      - in: query
        name: data_source_id
        type: string
        required: false
    responses:
      200:
        description: The caller's policies.
        schema:
          type: array
          items:
            $ref: "#/definitions/RetentionPolicy"
    """
    stmt = db.select(RetentionPolicy).filter_by(owner_id=get_jwt_identity())
    data_source_id = request.args.get("data_source_id")
    if data_source_id:
        stmt = stmt.filter_by(data_source_id=data_source_id)
    policies = db.session.scalars(stmt).all()
    return jsonify([p.to_dict() for p in policies]), 200


@retention_policies_bp.route("/policies/<policy_id>", methods=["GET"])
@jwt_required()
def get_policy(policy_id):
    """Get one retention policy.
    ---
    tags:
      - Retention Policies
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: policy_id
        type: string
        required: true
    responses:
      200:
        description: The policy.
        schema:
          $ref: "#/definitions/RetentionPolicy"
      404:
        description: No such policy, or it isn't owned by the caller.
    """
    policy, error = _get_owned_policy(policy_id)
    if error:
        return error
    return jsonify(policy.to_dict()), 200


@retention_policies_bp.route("/policies/<policy_id>", methods=["PATCH"])
@jwt_required()
def update_policy(policy_id):
    """Update a retention policy.
    Only the fields present in the body are changed.
    ---
    tags:
      - Retention Policies
    security:
      - BearerAuth: []
    consumes:
      - application/json
    parameters:
      - in: path
        name: policy_id
        type: string
        required: true
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            inactive_days:
              type: integer
            action:
              type: string
              enum: [anonymise, delete, flag]
            enabled:
              type: boolean
            schedule_interval_minutes:
              type: integer
    responses:
      200:
        description: The updated policy.
        schema:
          $ref: "#/definitions/RetentionPolicy"
      400:
        description: Request body is not a JSON object, or a provided field is invalid.
      404:
        description: No such policy, or it isn't owned by the caller.
    """
    policy, error = _get_owned_policy(policy_id)
    if error:
        return error
    data, error = _json_body()
    if error:
        return error

    if "inactive_days" in data:
        inactive_days = data["inactive_days"]
        if not isinstance(inactive_days, int) or inactive_days <= 0:
            return jsonify({"error": "inactive_days must be a positive integer"}), 400
        policy.inactive_days = inactive_days
    if "action" in data:
        if data["action"] not in RetentionPolicy.VALID_ACTIONS:
            return jsonify({"error": f"action must be one of {RetentionPolicy.VALID_ACTIONS}"}), 400
        policy.action = data["action"]
    if "enabled" in data:
        policy.enabled = bool(data["enabled"])
    if "schedule_interval_minutes" in data:
        schedule_interval_minutes = data["schedule_interval_minutes"]
        if schedule_interval_minutes is not None and (not isinstance(schedule_interval_minutes, int) or schedule_interval_minutes <= 0):
            return jsonify({"error": "schedule_interval_minutes must be a positive integer or null"}), 400
        policy.schedule_interval_minutes = schedule_interval_minutes
        # Changing the schedule makes it due again immediately, rather than
        # waiting out whatever the old interval had left.
        policy.next_scan_due_at = None

    db.session.commit()
    return jsonify(policy.to_dict()), 200


@retention_policies_bp.route("/policies/<policy_id>", methods=["DELETE"])
@jwt_required()
def delete_policy(policy_id):
    """Delete a retention policy.
    ---
    tags:
      - Retention Policies
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: policy_id
        type: string
        required: true
    responses:
      204:
        description: Deleted.
      404:
        description: No such policy, or it isn't owned by the caller.
    """
    policy, error = _get_owned_policy(policy_id)
    if error:
        return error
    db.session.delete(policy)
    db.session.commit()
    return "", 204


# ── Internal: used by enforce_retention's scheduled sweep ──────────────────

@retention_policies_bp.route("/internal/policies/due", methods=["GET"])
def list_due_policies_internal():
    """List enabled, scheduled policies that are due for a scan.
    Internal-only — enforce_retention's scheduled sweep polls this to find work, then claims each one via PATCH /internal/policies/<id>/claim before acting on it.
    ---
    tags:
      - Internal
    security:
      - InternalApiKey: []
    responses:
      200:
        description: Due policies.
        schema:
          type: array
          items:
            $ref: "#/definitions/RetentionPolicy"
      401:
        description: Missing or invalid X-Internal-Key header.
    """
    now = datetime.now(timezone.utc)
    stmt = db.select(RetentionPolicy).filter(
        RetentionPolicy.enabled.is_(True),
        RetentionPolicy.schedule_interval_minutes.isnot(None),
        db.or_(RetentionPolicy.next_scan_due_at.is_(None), RetentionPolicy.next_scan_due_at <= now),
    )
    policies = db.session.scalars(stmt).all()
    return jsonify([p.to_dict() for p in policies]), 200


@retention_policies_bp.route("/internal/policies/<policy_id>/claim", methods=["PATCH"])
def claim_policy_internal(policy_id):
    """Atomically claim a due policy for one scheduled scan.
    Internal-only. A compare-and-swap UPDATE, not a plain read-then-write: only succeeds if next_scan_due_at is still in the past at the moment of the UPDATE. If Cloud Run ever runs more than one instance of enforce_retention, every instance but the one whose UPDATE actually matched a row sees claimed=false and skips it — this is what prevents the same policy's scheduled scan from double-firing, without needing a distributed lock.
    ---
    tags:
      - Internal
    security:
      - InternalApiKey: []
    parameters:
      - in: path
        name: policy_id
        type: string
        required: true
    responses:
      200:
        description: Whether this call won the claim.
        schema:
          type: object
          properties:
            claimed:
              type: boolean
            policy:
              $ref: "#/definitions/RetentionPolicy"
      401:
        description: Missing or invalid X-Internal-Key header.
      404:
        description: No such policy.
    """
    policy = db.session.get(RetentionPolicy, policy_id)
    if policy is None:
        return jsonify({"error": "policy not found"}), 404

    now = datetime.now(timezone.utc)
    result = db.session.execute(
        db.update(RetentionPolicy)
        .where(
            RetentionPolicy.policy_id == policy_id,
            db.or_(RetentionPolicy.next_scan_due_at.is_(None), RetentionPolicy.next_scan_due_at <= now),
        )
        .values(
            next_scan_due_at=now + timedelta(minutes=policy.schedule_interval_minutes or 0),
            last_scan_at=now,
        )
    )
    db.session.commit()
    claimed = result.rowcount > 0
    db.session.refresh(policy)
    return jsonify({"claimed": claimed, "policy": policy.to_dict()}), 200


@retention_policies_bp.get("/health")
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
