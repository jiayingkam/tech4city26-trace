from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from .db import db
from .models import ScanRun, RetentionAction

audit_log_bp = Blueprint("audit_log", __name__)


def _json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, (jsonify({"error": "request body must be a JSON object"}), 400)
    return data, None


def _get_owned_scan_run(scan_run_id):
    run = db.session.get(ScanRun, scan_run_id)
    if run is None or run.owner_id != get_jwt_identity():
        return None, (jsonify({"error": "scan run not found"}), 404)
    return run, None


def _get_owned_action(action_id):
    action = db.session.get(RetentionAction, action_id)
    if action is None or action.owner_id != get_jwt_identity():
        return None, (jsonify({"error": "action not found"}), 404)
    return action, None


# ── Scan runs ────────────────────────────────────────────────────────────
# Every route here is JWT-protected, same as any other atomic service —
# enforce_retention forwards the caller's own Authorization header (their
# real session, or the 5-minute impersonation token minted for a scheduled
# sweep) rather than re-deriving identity, same pattern as manage_history
# calling detections/quarantine_items.

@audit_log_bp.route("/scan-runs", methods=["POST"])
@jwt_required()
def create_scan_run():
    """Start a new scan run.
    Called by enforce_retention at the start of every dry-run or enforce pass.
    ---
    tags:
      - Scan Runs
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
            - policy_id
            - data_source_id
            - mode
          properties:
            policy_id:
              type: string
            data_source_id:
              type: string
            mode:
              type: string
              enum: [dry_run, enforce]
    responses:
      201:
        description: The created scan run, status "running".
        schema:
          $ref: "#/definitions/ScanRun"
      400:
        description: Request body is not a JSON object, a required field is missing, or mode is invalid.
    """
    data, error = _json_body()
    if error:
        return error
    policy_id = data.get("policy_id")
    data_source_id = data.get("data_source_id")
    mode = data.get("mode")
    if not policy_id or not data_source_id or mode not in ScanRun.VALID_MODES:
        return jsonify({"error": f"policy_id, data_source_id, and mode (one of {ScanRun.VALID_MODES}) are required"}), 400

    run = ScanRun(owner_id=get_jwt_identity(), policy_id=policy_id, data_source_id=data_source_id, mode=mode)
    db.session.add(run)
    db.session.commit()
    return jsonify(run.to_dict()), 201


@audit_log_bp.route("/scan-runs/<scan_run_id>", methods=["PATCH"])
@jwt_required()
def update_scan_run(scan_run_id):
    """Update a scan run's progress/outcome.
    Called by enforce_retention as it counts rows and again when the run finishes (status becomes "completed" or "failed").
    ---
    tags:
      - Scan Runs
    security:
      - BearerAuth: []
    consumes:
      - application/json
    parameters:
      - in: path
        name: scan_run_id
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
              enum: [running, completed, failed]
            rows_scanned:
              type: integer
            rows_matched:
              type: integer
            error_detail:
              type: string
            finished:
              type: boolean
              description: Set true to stamp finished_at as now.
    responses:
      200:
        description: The updated scan run.
        schema:
          $ref: "#/definitions/ScanRun"
      400:
        description: Request body is not a JSON object, or status is invalid.
      404:
        description: No such scan run, or it isn't owned by the caller.
    """
    run, error = _get_owned_scan_run(scan_run_id)
    if error:
        return error
    data, error = _json_body()
    if error:
        return error

    if "status" in data:
        if data["status"] not in ScanRun.VALID_STATUSES:
            return jsonify({"error": f"status must be one of {ScanRun.VALID_STATUSES}"}), 400
        run.status = data["status"]
    if "rows_scanned" in data:
        run.rows_scanned = int(data["rows_scanned"])
    if "rows_matched" in data:
        run.rows_matched = int(data["rows_matched"])
    if "error_detail" in data:
        run.error_detail = data["error_detail"]
    if data.get("finished"):
        run.finished_at = datetime.now(timezone.utc)

    db.session.commit()
    return jsonify(run.to_dict()), 200


@audit_log_bp.route("/scan-runs", methods=["GET"])
@jwt_required()
def list_scan_runs():
    """List the caller's scan runs, most recent first.
    ---
    tags:
      - Scan Runs
    security:
      - BearerAuth: []
    parameters:
      - in: query
        name: policy_id
        type: string
        required: false
      - in: query
        name: data_source_id
        type: string
        required: false
    responses:
      200:
        description: The caller's scan runs.
        schema:
          type: array
          items:
            $ref: "#/definitions/ScanRun"
    """
    stmt = db.select(ScanRun).filter_by(owner_id=get_jwt_identity())
    policy_id = request.args.get("policy_id")
    if policy_id:
        stmt = stmt.filter_by(policy_id=policy_id)
    data_source_id = request.args.get("data_source_id")
    if data_source_id:
        stmt = stmt.filter_by(data_source_id=data_source_id)
    stmt = stmt.order_by(ScanRun.started_at.desc())
    runs = db.session.scalars(stmt).all()
    return jsonify([r.to_dict() for r in runs]), 200


@audit_log_bp.route("/scan-runs/<scan_run_id>", methods=["GET"])
@jwt_required()
def get_scan_run(scan_run_id):
    """Get one scan run.
    ---
    tags:
      - Scan Runs
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: scan_run_id
        type: string
        required: true
    responses:
      200:
        description: The scan run.
        schema:
          $ref: "#/definitions/ScanRun"
      404:
        description: No such scan run, or it isn't owned by the caller.
    """
    run, error = _get_owned_scan_run(scan_run_id)
    if error:
        return error
    return jsonify(run.to_dict()), 200


# ── Retention actions ────────────────────────────────────────────────────

@audit_log_bp.route("/actions", methods=["POST"])
@jwt_required()
def create_actions():
    """Record one or more proposed retention actions from a dry-run scan.
    Accepts a batch so a single scan's matches (potentially many rows) are recorded in one call rather than one round trip per row.
    ---
    tags:
      - Retention Actions
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
            - actions
          properties:
            actions:
              type: array
              items:
                type: object
                required:
                  - scan_run_id
                  - policy_id
                  - subject_id_value
                  - action_type
                properties:
                  scan_run_id:
                    type: string
                  policy_id:
                    type: string
                  subject_id_value:
                    type: string
                  action_type:
                    type: string
                    enum: [anonymise, delete, flag]
    responses:
      201:
        description: The created actions, status "proposed".
        schema:
          type: array
          items:
            $ref: "#/definitions/RetentionAction"
      400:
        description: Request body is not a JSON object, actions is missing/empty, or an entry is invalid.
    """
    data, error = _json_body()
    if error:
        return error
    entries = data.get("actions")
    if not isinstance(entries, list) or not entries:
        return jsonify({"error": "actions must be a non-empty array"}), 400

    owner_id = get_jwt_identity()
    created = []
    for entry in entries:
        if not isinstance(entry, dict):
            return jsonify({"error": "each action entry must be an object"}), 400
        scan_run_id = entry.get("scan_run_id")
        policy_id = entry.get("policy_id")
        subject_id_value = entry.get("subject_id_value")
        action_type = entry.get("action_type")
        if not scan_run_id or not policy_id or not subject_id_value or action_type not in RetentionAction.VALID_ACTION_TYPES:
            return jsonify({"error": "each action entry needs scan_run_id, policy_id, subject_id_value, and a valid action_type"}), 400
        created.append(RetentionAction(
            owner_id=owner_id,
            scan_run_id=scan_run_id,
            policy_id=policy_id,
            subject_id_value=subject_id_value,
            action_type=action_type,
        ))

    db.session.add_all(created)
    db.session.commit()
    return jsonify([a.to_dict() for a in created]), 201


@audit_log_bp.route("/actions", methods=["GET"])
@jwt_required()
def list_actions():
    """List the caller's retention actions.
    ---
    tags:
      - Retention Actions
    security:
      - BearerAuth: []
    parameters:
      - in: query
        name: policy_id
        type: string
        required: false
      - in: query
        name: scan_run_id
        type: string
        required: false
      - in: query
        name: status
        type: string
        enum: [proposed, approved, applied, failed]
        required: false
      - in: query
        name: subject_id_value
        type: string
        required: false
        description: Used by enforce_retention's dry-run idempotency check to see if a subject already has an applied action for a policy.
    responses:
      200:
        description: Matching actions.
        schema:
          type: array
          items:
            $ref: "#/definitions/RetentionAction"
      400:
        description: status is not a valid value.
    """
    stmt = db.select(RetentionAction).filter_by(owner_id=get_jwt_identity())
    policy_id = request.args.get("policy_id")
    if policy_id:
        stmt = stmt.filter_by(policy_id=policy_id)
    scan_run_id = request.args.get("scan_run_id")
    if scan_run_id:
        stmt = stmt.filter_by(scan_run_id=scan_run_id)
    status = request.args.get("status")
    if status:
        if status not in RetentionAction.VALID_STATUSES:
            return jsonify({"error": f"status must be one of {RetentionAction.VALID_STATUSES}"}), 400
        stmt = stmt.filter_by(status=status)
    subject_id_value = request.args.get("subject_id_value")
    if subject_id_value:
        stmt = stmt.filter_by(subject_id_value=subject_id_value)
    actions = db.session.scalars(stmt).all()
    return jsonify([a.to_dict() for a in actions]), 200


@audit_log_bp.route("/actions/<action_id>", methods=["PATCH"])
@jwt_required()
def update_action(action_id):
    """Update a retention action's status (e.g. approve it, or record enforcement's outcome).
    ---
    tags:
      - Retention Actions
    security:
      - BearerAuth: []
    consumes:
      - application/json
    parameters:
      - in: path
        name: action_id
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
              enum: [proposed, approved, applied, failed]
            detail:
              type: string
            applied:
              type: boolean
              description: Set true to stamp applied_at as now.
    responses:
      200:
        description: The updated action.
        schema:
          $ref: "#/definitions/RetentionAction"
      400:
        description: Request body is not a JSON object, or status is invalid.
      404:
        description: No such action, or it isn't owned by the caller.
    """
    action, error = _get_owned_action(action_id)
    if error:
        return error
    data, error = _json_body()
    if error:
        return error

    if "status" in data:
        if data["status"] not in RetentionAction.VALID_STATUSES:
            return jsonify({"error": f"status must be one of {RetentionAction.VALID_STATUSES}"}), 400
        action.status = data["status"]
    if "detail" in data:
        action.detail = data["detail"]
    if data.get("applied"):
        action.applied_at = datetime.now(timezone.utc)

    db.session.commit()
    return jsonify(action.to_dict()), 200


@audit_log_bp.get("/health")
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
