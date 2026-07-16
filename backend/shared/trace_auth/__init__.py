from datetime import timedelta
from os import environ
from flask import jsonify, request
from flask_jwt_extended import JWTManager, verify_jwt_in_request
from flask_jwt_extended.exceptions import JWTExtendedException
from jwt.exceptions import PyJWTError

# Maintenance endpoints (the retention sweep) have no logged-in user driving
# them, so they're gated by a shared static key instead of a user token.
INTERNAL_PREFIX = "/internal/"


def init_auth(app, *, public_paths=()):
    """Configures JWT verification and registers a global before_request gate.
    Every request needs a valid access token except /health, /swagger*, any
    explicitly listed public_paths (e.g. signup/login), and anything under
    /internal/, which is checked against INTERNAL_API_KEY instead.

    Single source of truth for every service's auth gate — copied into each
    service's container at build time (see each Dockerfile's
    `COPY shared/trace_auth trace_auth/`) rather than pip-published, since
    these are locally-built Compose services with no package index of their
    own."""
    app.config["JWT_SECRET_KEY"] = environ["JWT_SECRET_KEY"]
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=24)
    JWTManager(app)
    internal_api_key = environ.get("INTERNAL_API_KEY")

    @app.before_request
    def _require_auth():
        if request.path == "/health" or request.path.startswith("/swagger") or request.path in public_paths:
            return
        if request.path.startswith(INTERNAL_PREFIX):
            if not internal_api_key or request.headers.get("X-Internal-Key") != internal_api_key:
                return jsonify({"error": "invalid or missing internal key"}), 401
            return
        try:
            verify_jwt_in_request()
        except (JWTExtendedException, PyJWTError):
            return jsonify({"error": "authentication required"}), 401


def forwarded_auth_headers(request):
    """Composites don't re-derive identity themselves — they pass the
    caller's own Authorization header on to whatever atomic/composite
    service they call next, so that downstream service's own auth gate
    authenticates and authorizes the original caller, not the composite."""
    auth_header = request.headers.get("Authorization")
    return {"Authorization": auth_header} if auth_header else {}
