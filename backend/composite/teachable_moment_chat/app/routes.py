from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity
from trace_auth import forwarded_auth_headers

from .agent import ChatError, answer

bp = Blueprint("teachable_moment_chat", __name__)


@bp.post("/drafts/<draft_id>/chat")
def chat(draft_id):
    """Chat with the cyber-safety coach about this draft.
    Answers questions grounded in the draft's real detection/quarantine/exposure data,
    and runs a short interactive simulation (phishing, identity theft, or physical
    safety risk) depending on what was actually flagged.
    ---
    tags:
      - Teachable Moment Chat
    security:
      - BearerAuth: []
    consumes:
      - application/json
    parameters:
      - in: path
        name: draft_id
        type: string
        required: true
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - message
          properties:
            message:
              type: string
              description: The user's chat message.
            history:
              type: array
              description: Prior turns in this conversation, oldest first.
              items:
                type: object
                properties:
                  role:
                    type: string
                    enum: [user, assistant]
                  content:
                    type: string
    responses:
      200:
        description: The coach's reply.
        schema:
          id: TeachableMomentChatReply
          type: object
          properties:
            reply:
              type: string
      400:
        description: Request body is missing 'message'.
      502:
        description: The agent or one of its grounding calls failed.
    """
    body = request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()
    history = body.get("history") or []
    if not message:
        return jsonify({"error": "message is required"}), 400

    try:
        reply = answer(
            draft_id=draft_id,
            message=message,
            history=history,
            auth_headers=forwarded_auth_headers(request),
            owner_id=get_jwt_identity(),
        )
    except ChatError:
        return jsonify({"error": "failed to generate a reply"}), 502

    return jsonify({"reply": reply}), 200


# In professional setups, a Load Balancer and/or caller pings this /health URL every few seconds.
# If your code gets stuck in an infinite loop during a request,
# it will stop responding to /health.
@bp.get("/health")
def health():
    """Liveness check.
    Unauthenticated — polled frequently by the container orchestrator.
    ---
    tags:
      - Health
    responses:
      200:
        description: The service process is alive.
    """
    return jsonify({"status": "ok"}), 200
