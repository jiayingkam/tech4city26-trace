from datetime import timedelta
from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from werkzeug.security import generate_password_hash, check_password_hash
from .db import db
from .models import BusinessAdmin

business_admins_bp = Blueprint("business_admins", __name__)


def _json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, (jsonify({"error": "request body must be a JSON object"}), 400)
    return data, None


@business_admins_bp.route("/signup", methods=["POST"])
def signup():
    """Register a new business account.
    Public — no authentication required. Returns an access token so the caller is signed in immediately.
    ---
    tags:
      - Business Admins
    consumes:
      - application/json
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - email
            - password
            - business_name
          properties:
            email:
              type: string
              example: admin@fakecorp.com
            password:
              type: string
              format: password
            business_name:
              type: string
              example: FakeCorp Pte Ltd
    responses:
      201:
        description: Account created.
        schema:
          id: AuthResponse
          type: object
          properties:
            token:
              type: string
            admin:
              id: BusinessAdmin
              type: object
              properties:
                admin_id:
                  type: string
                email:
                  type: string
                business_name:
                  type: string
                created_at:
                  type: string
                  format: date-time
      400:
        description: Request body is not a JSON object, or email/password/business_name is missing.
      409:
        description: An account with that email already exists.
    """
    data, error = _json_body()
    if error:
        return error
    email = data.get("email")
    password = data.get("password")
    business_name = data.get("business_name")
    if not email or not password or not business_name:
        return jsonify({"error": "email, password, and business_name are required"}), 400
    if db.session.scalar(db.select(BusinessAdmin).filter_by(email=email)):
        return jsonify({"error": "an account with that email already exists"}), 409

    admin = BusinessAdmin(email=email, password_hash=generate_password_hash(password), business_name=business_name)
    db.session.add(admin)
    db.session.commit()
    token = create_access_token(identity=admin.admin_id)
    return jsonify({"token": token, "admin": admin.to_dict()}), 201


@business_admins_bp.route("/login", methods=["POST"])
def login():
    """Log in with email and password.
    Public — no authentication required.
    ---
    tags:
      - Business Admins
    consumes:
      - application/json
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - email
            - password
          properties:
            email:
              type: string
              example: admin@fakecorp.com
            password:
              type: string
              format: password
    responses:
      200:
        description: Logged in.
        schema:
          $ref: "#/definitions/AuthResponse"
      400:
        description: Request body is not a JSON object, or email/password is missing.
      401:
        description: Invalid email or password.
    """
    data, error = _json_body()
    if error:
        return error
    email = data.get("email")
    password = data.get("password")
    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    admin = db.session.scalar(db.select(BusinessAdmin).filter_by(email=email))
    if not admin or not check_password_hash(admin.password_hash, password):
        return jsonify({"error": "Invalid email or password"}), 401

    token = create_access_token(identity=admin.admin_id)
    return jsonify({"token": token, "admin": admin.to_dict()}), 200


@business_admins_bp.route("/logout", methods=["POST"])
@jwt_required()
def logout():
    """Log out the current admin.
    Access tokens are stateless and not revoked server-side; this endpoint exists so the frontend has something symmetrical to call — the actual sign-out is the client discarding its token.
    ---
    tags:
      - Business Admins
    security:
      - BearerAuth: []
    responses:
      200:
        description: Acknowledged.
    """
    return jsonify({"status": "ok"}), 200


@business_admins_bp.route("/me", methods=["GET"])
@jwt_required()
def get_me():
    """Get the authenticated admin's profile.
    ---
    tags:
      - Business Admins
    security:
      - BearerAuth: []
    responses:
      200:
        description: The current admin.
        schema:
          $ref: "#/definitions/BusinessAdmin"
      404:
        description: No admin found for the authenticated identity.
    """
    admin = db.session.get(BusinessAdmin, get_jwt_identity())
    if admin is None:
        return jsonify({"error": "admin not found"}), 404
    return jsonify(admin.to_dict()), 200


# Internal-only: lets enforce_retention's scheduled sweep act as the owning
# admin of a due policy without needing a per-admin login token — mirrors
# TRACE's users.impersonate_internal exactly (see plan §Auth).
@business_admins_bp.route("/internal/impersonate", methods=["POST"])
def impersonate_internal():
    """Mint a short-lived access token for a given business admin.
    Internal-only — lets the retention scan scheduler (which has no logged-in admin driving it) re-use the same authenticated/authorized code paths as a real request, scoped to the one admin whose policy is due.
    ---
    tags:
      - Internal
    security:
      - InternalApiKey: []
    consumes:
      - application/json
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - admin_id
          properties:
            admin_id:
              type: string
    responses:
      200:
        description: A short-lived (5 minute) access token for the given admin.
        schema:
          type: object
          properties:
            token:
              type: string
      400:
        description: Request body is not a JSON object.
      401:
        description: Missing or invalid X-Internal-Key header.
      404:
        description: admin_id is missing or no admin with that id exists.
    """
    data, error = _json_body()
    if error:
        return error
    admin_id = data.get("admin_id")
    if not admin_id or db.session.get(BusinessAdmin, admin_id) is None:
        return jsonify({"error": "admin not found"}), 404
    # Short-lived — only needs to survive one scheduled scan's worth of requests.
    token = create_access_token(identity=admin_id, expires_delta=timedelta(minutes=5))
    return jsonify({"token": token}), 200


@business_admins_bp.get("/health")
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
