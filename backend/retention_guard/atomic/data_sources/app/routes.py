from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from trace_crypto import encrypt, decrypt
from .db import db
from .models import DataSource, ClassifiedColumn

data_sources_bp = Blueprint("data_sources", __name__)

VALID_DB_TYPES = ("postgresql",)  # MVP scope — see plan's corner-cuts list


def _json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, (jsonify({"error": "request body must be a JSON object"}), 400)
    return data, None


def _get_owned_source(data_source_id):
    """Returns (source, error_response). error_response is set for both a
    missing row and one owned by someone else — a 404 either way, so a caller
    probing IDs can't distinguish "doesn't exist" from "not yours"."""
    source = db.session.get(DataSource, data_source_id)
    if source is None or source.owner_id != get_jwt_identity():
        return None, (jsonify({"error": "data source not found"}), 404)
    return source, None


@data_sources_bp.route("/data-sources", methods=["POST"])
@jwt_required()
def create_data_source():
    """Register a new external database connection.
    The connection string is encrypted at rest immediately and never echoed back by any route except the internal connection-fetch route.
    ---
    tags:
      - Data Sources
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
            - name
            - connection_string
          properties:
            name:
              type: string
              example: FakeCorp Customer DB
            db_type:
              type: string
              enum: [postgresql]
              default: postgresql
            connection_string:
              type: string
              example: postgresql://user:pass@host:5432/fakecorp
    responses:
      201:
        description: The registered data source (connection string omitted).
        schema:
          $ref: "#/definitions/DataSource"
      400:
        description: Request body is not a JSON object, name/connection_string is missing, or db_type is unsupported.
    """
    data, error = _json_body()
    if error:
        return error
    name = data.get("name")
    connection_string = data.get("connection_string")
    db_type = data.get("db_type", "postgresql")
    if not name or not connection_string:
        return jsonify({"error": "name and connection_string are required"}), 400
    if db_type not in VALID_DB_TYPES:
        return jsonify({"error": f"db_type must be one of {VALID_DB_TYPES}"}), 400

    source = DataSource(
        owner_id=get_jwt_identity(),
        name=name,
        db_type=db_type,
        connection_string_encrypted=encrypt(connection_string),
    )
    db.session.add(source)
    db.session.commit()
    return jsonify(source.to_dict()), 201


@data_sources_bp.route("/data-sources", methods=["GET"])
@jwt_required()
def list_data_sources():
    """List the caller's registered data sources.
    ---
    tags:
      - Data Sources
    security:
      - BearerAuth: []
    responses:
      200:
        description: The caller's data sources.
        schema:
          type: array
          items:
            $ref: "#/definitions/DataSource"
    """
    sources = db.session.scalars(db.select(DataSource).filter_by(owner_id=get_jwt_identity())).all()
    return jsonify([s.to_dict() for s in sources]), 200


@data_sources_bp.route("/data-sources/<data_source_id>", methods=["GET"])
@jwt_required()
def get_data_source(data_source_id):
    """Get one data source.
    ---
    tags:
      - Data Sources
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: data_source_id
        type: string
        required: true
    responses:
      200:
        description: The data source.
        schema:
          $ref: "#/definitions/DataSource"
      404:
        description: No such data source, or it isn't owned by the caller.
    """
    source, error = _get_owned_source(data_source_id)
    if error:
        return error
    return jsonify(source.to_dict()), 200


@data_sources_bp.route("/data-sources/<data_source_id>", methods=["DELETE"])
@jwt_required()
def delete_data_source(data_source_id):
    """Delete a data source and its column classifications.
    Does not touch the external database itself — only this service's own record of it.
    ---
    tags:
      - Data Sources
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: data_source_id
        type: string
        required: true
    responses:
      204:
        description: Deleted.
      404:
        description: No such data source, or it isn't owned by the caller.
    """
    source, error = _get_owned_source(data_source_id)
    if error:
        return error
    db.session.execute(db.delete(ClassifiedColumn).filter_by(data_source_id=data_source_id))
    db.session.delete(source)
    db.session.commit()
    return "", 204


@data_sources_bp.route("/data-sources/<data_source_id>/classified-columns", methods=["POST"])
@jwt_required()
def create_classified_column(data_source_id):
    """Tag a column on this data source with its role.
    ---
    tags:
      - Classified Columns
    security:
      - BearerAuth: []
    consumes:
      - application/json
    parameters:
      - in: path
        name: data_source_id
        type: string
        required: true
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - table_name
            - column_name
            - column_role
          properties:
            table_name:
              type: string
              example: customers
            column_name:
              type: string
              example: email
            column_role:
              type: string
              enum: [pii, subject_id, activity_timestamp]
    responses:
      201:
        description: The classified column.
        schema:
          $ref: "#/definitions/ClassifiedColumn"
      400:
        description: Request body is not a JSON object, a required field is missing, or column_role is invalid.
      404:
        description: No such data source, or it isn't owned by the caller.
    """
    source, error = _get_owned_source(data_source_id)
    if error:
        return error
    data, error = _json_body()
    if error:
        return error
    table_name = data.get("table_name")
    column_name = data.get("column_name")
    column_role = data.get("column_role")
    if not table_name or not column_name or not column_role:
        return jsonify({"error": "table_name, column_name, and column_role are required"}), 400
    if column_role not in ClassifiedColumn.VALID_ROLES:
        return jsonify({"error": f"column_role must be one of {ClassifiedColumn.VALID_ROLES}"}), 400

    column = ClassifiedColumn(
        data_source_id=source.data_source_id,
        table_name=table_name,
        column_name=column_name,
        column_role=column_role,
    )
    db.session.add(column)
    db.session.commit()
    return jsonify(column.to_dict()), 201


@data_sources_bp.route("/data-sources/<data_source_id>/classified-columns", methods=["GET"])
@jwt_required()
def list_classified_columns(data_source_id):
    """List a data source's classified columns.
    ---
    tags:
      - Classified Columns
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: data_source_id
        type: string
        required: true
      - in: query
        name: table_name
        type: string
        required: false
        description: Restrict to columns classified on this table.
    responses:
      200:
        description: The classified columns.
        schema:
          type: array
          items:
            $ref: "#/definitions/ClassifiedColumn"
      404:
        description: No such data source, or it isn't owned by the caller.
    """
    source, error = _get_owned_source(data_source_id)
    if error:
        return error
    stmt = db.select(ClassifiedColumn).filter_by(data_source_id=source.data_source_id)
    table_name = request.args.get("table_name")
    if table_name:
        stmt = stmt.filter_by(table_name=table_name)
    columns = db.session.scalars(stmt).all()
    return jsonify([c.to_dict() for c in columns]), 200


@data_sources_bp.route("/classified-columns/<classified_column_id>", methods=["DELETE"])
@jwt_required()
def delete_classified_column(classified_column_id):
    """Remove a column classification.
    ---
    tags:
      - Classified Columns
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: classified_column_id
        type: string
        required: true
    responses:
      204:
        description: Deleted.
      404:
        description: No such classified column, or its data source isn't owned by the caller.
    """
    column = db.session.get(ClassifiedColumn, classified_column_id)
    if column is None:
        return jsonify({"error": "classified column not found"}), 404
    _, error = _get_owned_source(column.data_source_id)
    if error:
        return error
    db.session.delete(column)
    db.session.commit()
    return "", 204


# Internal-only: the one code path in the whole product that ever produces a
# plaintext connection string. enforce_retention calls this to get a DSN it
# can open a live connection with — it never holds the encryption key itself
# (see shared/trace_crypto and the plan's Encryption section).
@data_sources_bp.route("/internal/data-sources/<data_source_id>/connection", methods=["GET"])
def get_connection_internal(data_source_id):
    """Get the decrypted connection string for a data source.
    Internal-only — enforce_retention uses this to open a live connection to the external source. Never exposed on the caller-facing GET /data-sources/<id> route.
    ---
    tags:
      - Internal
    security:
      - InternalApiKey: []
    parameters:
      - in: path
        name: data_source_id
        type: string
        required: true
    responses:
      200:
        description: The decrypted connection string.
        schema:
          type: object
          properties:
            connection_string:
              type: string
            db_type:
              type: string
      401:
        description: Missing or invalid X-Internal-Key header.
      404:
        description: No such data source.
    """
    source = db.session.get(DataSource, data_source_id)
    if source is None:
        return jsonify({"error": "data source not found"}), 404
    return jsonify({
        "connection_string": decrypt(source.connection_string_encrypted),
        "db_type": source.db_type,
    }), 200


@data_sources_bp.get("/health")
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
