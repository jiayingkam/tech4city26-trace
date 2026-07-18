from flask import Blueprint, jsonify

bp = Blueprint("update_exposure_profile", __name__)

# yr functions/routes here


# In professional setups, a Load Balancer and/or caller pings this /health URL every few seconds.
# If your code gets stuck in an infinite loop during a request,
# it will stop responding to /health.
@bp.get("/health")
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
