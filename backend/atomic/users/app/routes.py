from datetime import timedelta
from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from werkzeug.security import generate_password_hash, check_password_hash
from .db import db
from .models import User

users_bp = Blueprint("users", __name__)

VALID_RETENTION_MODES = ("auto_expire", "manual")


def _json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, (jsonify({"error": "request body must be a JSON object"}), 400)
    return data, None


@users_bp.route("/signup", methods=["POST"])
def signup():
    """Create a new user account.
    Public — no authentication required. Returns an access token so the caller is signed in immediately.
    ---
    tags:
      - Users
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
              example: user@example.com
            password:
              type: string
              format: password
    responses:
      201:
        description: Account created.
        schema:
          id: AuthResponse
          type: object
          properties:
            token:
              type: string
            user:
              id: User
              type: object
              properties:
                user_id:
                  type: string
                email:
                  type: string
                retention_mode:
                  type: string
                  enum: [auto_expire, manual]
                created_at:
                  type: string
                  format: date-time
      400:
        description: Request body is not a JSON object, or email/password is missing.
      409:
        description: An account with that email already exists.
    """
    data, error = _json_body()
    if error:
        return error
    email = data.get("email")
    password = data.get("password")
    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400
    if db.session.scalar(db.select(User).filter_by(email=email)):
        return jsonify({"error": "an account with that email already exists"}), 409

    user = User(email=email, password_hash=generate_password_hash(password))
    db.session.add(user)
    db.session.commit()
    token = create_access_token(identity=user.user_id)
    return jsonify({"token": token, "user": user.to_dict()}), 201


@users_bp.route("/login", methods=["POST"])
def login():
    """Log in with email and password.
    Public — no authentication required.
    ---
    tags:
      - Users
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
              example: user@example.com
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

    user = db.session.scalar(db.select(User).filter_by(email=email))
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "Invalid email or password"}), 401

    token = create_access_token(identity=user.user_id)
    return jsonify({"token": token, "user": user.to_dict()}), 200


@users_bp.route("/logout", methods=["POST"])
@jwt_required()
def logout():
    """Log out the current user.
    Access tokens are stateless and not revoked server-side; this endpoint exists so the frontend has something symmetrical to call — the actual sign-out is the client discarding its token.
    ---
    tags:
      - Users
    security:
      - BearerAuth: []
    responses:
      200:
        description: Acknowledged.
    """
    # Access tokens are stateless and not revoked server-side (short-lived,
    # by design — see the plan's trade-off note). This route exists so the
    # frontend has something symmetrical to call; the actual sign-out is the
    # client discarding its token.
    return jsonify({"status": "ok"}), 200


@users_bp.route("/me", methods=["GET"])
@jwt_required()
def get_me():
    """Get the authenticated user's profile.
    ---
    tags:
      - Users
    security:
      - BearerAuth: []
    responses:
      200:
        description: The current user.
        schema:
          $ref: "#/definitions/User"
      404:
        description: No user found for the authenticated identity.
    """
    user = db.session.get(User, get_jwt_identity())
    if user is None:
        return jsonify({"error": "user not found"}), 404
    return jsonify(user.to_dict()), 200


@users_bp.route("/users/<user_id>/settings", methods=["PATCH"])
@jwt_required()
def update_settings(user_id):
    """Update a user's retention mode.
    user_id must match the authenticated caller.
    ---
    tags:
      - Users
    security:
      - BearerAuth: []
    consumes:
      - application/json
    parameters:
      - in: path
        name: user_id
        type: string
        required: true
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - retention_mode
          properties:
            retention_mode:
              type: string
              enum: [auto_expire, manual]
    responses:
      200:
        description: The updated user.
        schema:
          $ref: "#/definitions/User"
      400:
        description: Request body is not a JSON object, or retention_mode is invalid.
      403:
        description: user_id does not match the authenticated user.
      404:
        description: No user with that id exists.
    """
    if user_id != get_jwt_identity():
        return jsonify({"error": "forbidden"}), 403
    user = db.session.get(User, user_id)
    if user is None:
        return jsonify({"error": "user not found"}), 404
    data, error = _json_body()
    if error:
        return error
    retention_mode = data.get("retention_mode")
    if retention_mode not in VALID_RETENTION_MODES:
        return jsonify({"error": "invalid retention_mode"}), 400

    user.retention_mode = retention_mode
    db.session.commit()
    return jsonify(user.to_dict()), 200


# Internal-only: lets manage_history's retention sweep find which users are
# on auto_expire without needing a per-user login token. Gated by the
# INTERNAL_API_KEY check in this service's before_request hook (any
# /internal/* path), not by the user-JWT hook.
@users_bp.route("/internal/users", methods=["GET"])
def list_users_internal():
    """List users, optionally filtered by retention mode.
    Internal-only — lets manage_history's retention sweep find which users are on auto_expire without a per-user login token.
    ---
    tags:
      - Internal
    security:
      - InternalApiKey: []
    parameters:
      - in: query
        name: retention_mode
        type: string
        enum: [auto_expire, manual]
        required: false
    responses:
      200:
        description: Matching users.
        schema:
          type: array
          items:
            $ref: "#/definitions/User"
      401:
        description: Missing or invalid X-Internal-Key header.
    """
    retention_mode = request.args.get("retention_mode")
    stmt = db.select(User)
    if retention_mode:
        stmt = stmt.filter_by(retention_mode=retention_mode)
    users = db.session.scalars(stmt).all()
    return jsonify([u.to_dict() for u in users]), 200


# Internal-only: every other service enforces ownership by checking a
# request's JWT identity against a record's owner_id — including the
# cascade-delete routes the retention sweep needs to call. But the sweep has
# no logged-in user driving it, so it has nothing to present there. This
# mints the same shape of token a real login would, scoped to the one user
# whose expired content it's about to clean up, so the sweep re-uses the
# exact same authenticated/authorized code paths as a real request instead
# of every route needing a second "or present the internal key" branch.
@users_bp.route("/internal/impersonate", methods=["POST"])
def impersonate_internal():
    """Mint a short-lived access token for a given user.
    Internal-only — lets the retention sweep (which has no logged-in user driving it) re-use the same authenticated/authorized code paths as a real request, scoped to the one user whose expired content it's about to clean up.
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
            - user_id
          properties:
            user_id:
              type: string
    responses:
      200:
        description: A short-lived (5 minute) access token for the given user.
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
        description: user_id is missing or no user with that id exists.
    """
    data, error = _json_body()
    if error:
        return error
    user_id = data.get("user_id")
    if not user_id or db.session.get(User, user_id) is None:
        return jsonify({"error": "user not found"}), 404
    # Short-lived — only needs to survive one sweep run's worth of requests.
    token = create_access_token(identity=user_id, expires_delta=timedelta(minutes=5))
    return jsonify({"token": token}), 200


# In professional setups, a Load Balancer and/or caller pings this /health URL every few seconds.
# If your code gets stuck in an infinite loop during a request,
# it will stop responding to /health.
@users_bp.get("/health")
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
