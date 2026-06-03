from flask import Blueprint, jsonify

bp = Blueprint("remediate_content", __name__)

# yr functions/routes here


# In professional setups, a Load Balancer and/or caller pings this /health URL every few seconds.
# If your code gets stuck in an infinite loop while scraping Reddit,
# it will stop responding to /health.
@bp.get("/health")
def health():
    return jsonify({"status": "ok"}), 200
