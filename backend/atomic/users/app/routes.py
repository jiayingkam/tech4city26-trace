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
    data, error = _json_body()
    if error:
        return error
    email = data.get("email")
    password = data.get("password")
    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    user = db.session.scalar(db.select(User).filter_by(email=email))
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "invalid email or password"}), 401

    token = create_access_token(identity=user.user_id)
    return jsonify({"token": token, "user": user.to_dict()}), 200


@users_bp.route("/logout", methods=["POST"])
@jwt_required()
def logout():
    # Access tokens are stateless and not revoked server-side (short-lived,
    # by design — see the plan's trade-off note). This route exists so the
    # frontend has something symmetrical to call; the actual sign-out is the
    # client discarding its token.
    return jsonify({"status": "ok"}), 200


@users_bp.route("/me", methods=["GET"])
@jwt_required()
def get_me():
    user = db.session.get(User, get_jwt_identity())
    if user is None:
        return jsonify({"error": "user not found"}), 404
    return jsonify(user.to_dict()), 200


@users_bp.route("/users/<user_id>/settings", methods=["PATCH"])
@jwt_required()
def update_settings(user_id):
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
    return jsonify({"status": "ok"}), 200
