import os
import requests
from flask import Blueprint, jsonify, request
from trace_auth import forwarded_auth_headers

bp = Blueprint("generate_teachable_moment", __name__)

DETECTIONS_SERVICE_URL = os.environ.get("DETECTIONS_SERVICE_URL", "http://detections:5003")

LESSONS = {
    "metadata": {
        "title": "Hidden location data found",
        "explanation": "This photo may carry GPS or device details that can reveal exactly where it was taken, even if nothing obvious is visible.",
        "safer_action": "Let Trace strip the hidden metadata before sharing.",
        "discussion_prompt": "What hidden information might travel with a photo after you post it?",
    },
    "location": {
        "title": "Location clue detected",
        "explanation": "Visible places, signs, block numbers, or address clues can help someone narrow down where you live, study, or spend time.",
        "safer_action": "Blur the location clue or choose a photo without identifying background details.",
        "discussion_prompt": "Which background details could reveal where someone lives or studies?",
    },
    "face": {
        "title": "Face detected",
        "explanation": "Faces can identify you or someone nearby, especially when combined with school, home, or routine details from other posts.",
        "safer_action": "Blur faces that do not need to be visible before sharing.",
        "discussion_prompt": "When should you ask someone before posting a photo that shows their face?",
    },
    "document": {
        "title": "Identifying detail found",
        "explanation": "Documents, uniforms, cards, and labels can connect a post to your school, workplace, address, or identity.",
        "safer_action": "Blur the identifying detail before posting.",
        "discussion_prompt": "What everyday objects in a photo could identify someone?",
    },
    "contact": {
        "title": "Contact detail found",
        "explanation": "Phone numbers, emails, and handles can let strangers contact you directly or connect this post to your real identity.",
        "safer_action": "Remove or redact the contact detail from your caption.",
        "discussion_prompt": "Which contact details should stay out of public posts?",
    },
    "financial": {
        "title": "Financial detail found",
        "explanation": "Receipts, card numbers, account details, and payment clues can expose private financial information.",
        "safer_action": "Blur or remove the financial detail before sharing.",
        "discussion_prompt": "What payment or receipt details should be hidden before posting?",
    },
    "credentials": {
        "title": "Access detail found",
        "explanation": "Passwords, codes, tickets, and QR passes can give someone access to an account, place, or event.",
        "safer_action": "Remove the access detail and regenerate the code if it may already be exposed.",
        "discussion_prompt": "Why are codes and passes risky even when they appear only briefly?",
    },
}

DEFAULT_LESSON = {
    "title": "Personal detail detected",
    "explanation": "This post includes a detail that could reveal more about you than intended when shared publicly.",
    "safer_action": "Review the flagged detail and edit it before posting.",
    "discussion_prompt": "What personal details are easy to miss before sharing a post?",
}


def _primary_detection(detections):
    if not detections:
        return None
    return max(
        detections,
        key=lambda d: (
            d.get("exposure_score") or 0,
            1 if d.get("category") == "metadata" else 0,
            1 if d.get("source_type") == "image" else 0,
        ),
    )


@bp.post("/drafts/<draft_id>/teachable-moment")
def generate_teachable_moment(draft_id):
    """Return a short, template-based micro-lesson for the riskiest finding.
    Fetches the draft's detections and turns the highest-priority finding into a short,
    template-based micro-lesson. Returns a generic "looks safe" lesson when there are no detections.
    ---
    tags:
      - Teachable Moment
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: draft_id
        type: string
        required: true
    responses:
      200:
        description: The generated micro-lesson.
        schema:
          id: TeachableMoment
          type: object
          properties:
            draft_id:
              type: string
            title:
              type: string
            explanation:
              type: string
            safer_action:
              type: string
            discussion_prompt:
              type: string
            category:
              type: string
              description: The detection category the lesson was generated for, or null when no detections were found.
            source_type:
              type: string
              description: Present only when a detection drove the lesson.
            exposure_score:
              type: number
            detail:
              type: string
              description: Present only when a detection drove the lesson.
            detection_count:
              type: integer
              description: Present only when a detection drove the lesson.
      502:
        description: Failed to fetch detections from the detections service.
    """
    resp = requests.get(
        f"{DETECTIONS_SERVICE_URL}/drafts/{draft_id}/detections",
        headers=forwarded_auth_headers(request),
    )
    if resp.status_code != 200:
        return jsonify({"error": "failed to fetch detections"}), 502

    detections = resp.json()
    primary = _primary_detection(detections)
    if primary is None:
        return jsonify({
            "draft_id": draft_id,
            "title": "Looks safe to share",
            "explanation": "Trace did not find personal details that need a warning in this post.",
            "safer_action": "You can still do a quick final check before posting.",
            "discussion_prompt": "What do you usually check before sharing a post?",
            "category": None,
            "exposure_score": 0,
        }), 200

    lesson = LESSONS.get(primary.get("category"), DEFAULT_LESSON)
    return jsonify({
        "draft_id": draft_id,
        **lesson,
        "category": primary.get("category"),
        "source_type": primary.get("source_type"),
        "exposure_score": primary.get("exposure_score"),
        "detail": primary.get("detail"),
        "detection_count": len(detections),
    }), 200

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
