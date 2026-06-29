import os
from flask import Blueprint, jsonify

bp = Blueprint("generate_teachable_moment", __name__)

# yr functions/routes here
@bp.post("/drafts/<draft_id>/teachable-moment")
def generate_teachable_moment(draft_id):
    """Minimal implementation to satisfy route and return a sample teachable moment.

    This is a placeholder until full integration with the detections service and LLM
    is implemented.
    """
    sample = {
        "draft_id": draft_id,
        "title": "Location clue detected",
        "explanation": "Your photo shows a block number. Combined with your caption, this could reveal where you live.",
        "safer_action": "Blur the block number before posting.",
        "discussion_prompt": "What details in a photo could reveal where someone lives?"
    }
    return jsonify(sample), 200
DETECTIONS_SERVICE_URL = os.environ.get(
    "DETECTIONS_SERVICE_URL",
    "http://detections:5003"
)

# In professional setups, a Load Balancer and/or caller pings this /health URL every few seconds.
# If your code gets stuck in an infinite loop during a request,
# it will stop responding to /health.
@bp.get("/health")
def health():
    return jsonify({"status": "ok"}), 200
