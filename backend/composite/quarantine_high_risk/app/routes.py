import os
import requests
from flask import Blueprint, request, jsonify

from trace_auth import forwarded_auth_headers

bp = Blueprint("quarantine_high_risk", __name__)

DETECTIONS_SERVICE_URL = os.environ.get("DETECTIONS_SERVICE_URL", "http://DETECTIONS:5003")
QUARANTINE_ITEMS_SERVICE_URL = os.environ.get("QUARANTINE_ITEMS_SERVICE_URL", "http://QUARANTINE_ITEMS:5006")
REMEDIATE_CONTENT_SERVICE_URL = os.environ.get("REMEDIATE_CONTENT_SERVICE_URL", "http://REMEDIATE_CONTENT:5011")


def _build_reason(detections):
    """Turn a list of high-risk detections into a plain-language hold reason."""
    categories = sorted({d["category"] for d in detections})
    return "High-risk content detected: " + ", ".join(categories)


def _set_high_risk_resolutions(draft_id, resolution, auth_headers):
    """Quarantine holds are decided per-draft, not per-detection, so release/
    delete resolve every detection that caused the hold (exposure >= 4) in
    one go — best-effort, same as remediate_content's equivalent helper."""
    resp = requests.get(f"{DETECTIONS_SERVICE_URL}/drafts/{draft_id}/detections", headers=auth_headers)
    if resp.status_code != 200:
        return
    for d in resp.json():
        if d["exposure_score"] >= 4:
            requests.patch(
                f"{DETECTIONS_SERVICE_URL}/detections/{d['detection_id']}",
                json={"resolution": resolution},
                headers=auth_headers,
            )


@bp.route("/drafts/<draft_id>/quarantine", methods=["POST"])
def quarantine_draft(draft_id):
    """Place a draft on quarantine hold.
    Fetches the draft's high-risk detections (exposure_score >= 4) and, if any exist, creates a quarantine hold for the draft with a plain-language reason built from their categories.
    ---
    tags:
      - Quarantine
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: draft_id
        type: string
        required: true
    responses:
      201:
        description: Quarantine hold created.
        schema:
          id: QuarantineItem
          type: object
          properties:
            quarantine_id:
              type: string
            draft_id:
              type: string
            owner_id:
              type: string
            reason:
              type: string
              example: "High-risk content detected: face, location"
            cooldown_expiry:
              type: string
              format: date-time
            state:
              type: string
              enum: [held, accepted, edited, deleted]
            created_at:
              type: string
              format: date-time
      400:
        description: No high-risk (exposure_score >= 4) detections were found for this draft.
      502:
        description: Failed to fetch detections from the detections service, or failed to create the quarantine item in the quarantine service.
    """
    auth_headers = forwarded_auth_headers(request)
    # 1. fetch detections, high risk only (exposure >= 4)
    resp = requests.get(f"{DETECTIONS_SERVICE_URL}/drafts/{draft_id}/detections", headers=auth_headers)
    if resp.status_code != 200:
        return jsonify({"error": "failed to fetch detections"}), 502
    detections = [d for d in resp.json() if d["exposure_score"] >= 4]
    if not detections:
        return jsonify({"error": "no high-risk detections found"}), 400

    # 2. create the quarantine hold
    payload = {
        "draft_id": draft_id,
        "reason": _build_reason(detections),
    }
    q_resp = requests.post(f"{QUARANTINE_ITEMS_SERVICE_URL}/quarantine", json=payload, headers=auth_headers)
    if q_resp.status_code != 201:
        return jsonify({"error": "failed to create quarantine item"}), 502

    return jsonify(q_resp.json()), 201


@bp.route("/drafts/<draft_id>/quarantine", methods=["GET"])
def get_draft_quarantine(draft_id):
    """List a draft's quarantine items with cooldown state.
    Fetches the draft's quarantine items and enriches each one with its current cooldown status.
    ---
    tags:
      - Quarantine
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: draft_id
        type: string
        required: true
    responses:
      200:
        description: The draft's quarantine items, each with its cooldown status. cooldown is {} if the cooldown lookup for that item failed.
        schema:
          type: array
          items:
            id: QuarantineItemWithCooldown
            type: object
            properties:
              quarantine_id:
                type: string
              draft_id:
                type: string
              owner_id:
                type: string
              reason:
                type: string
              cooldown_expiry:
                type: string
                format: date-time
              state:
                type: string
                enum: [held, accepted, edited, deleted]
              created_at:
                type: string
                format: date-time
              cooldown:
                id: CooldownStatus
                type: object
                properties:
                  quarantine_id:
                    type: string
                  expired:
                    type: boolean
                  seconds_remaining:
                    type: integer
                    description: Seconds until cooldown_expiry, floored at 0.
      502:
        description: Failed to fetch quarantine items from the quarantine service.
    """
    auth_headers = forwarded_auth_headers(request)
    resp = requests.get(f"{QUARANTINE_ITEMS_SERVICE_URL}/drafts/{draft_id}/quarantine", headers=auth_headers)
    if resp.status_code != 200:
        return jsonify({"error": "failed to fetch quarantine items"}), 502
    items = resp.json()

    # enrich each item with its cooldown state
    result = []
    for item in items:
        cooldown_resp = requests.get(
            f"{QUARANTINE_ITEMS_SERVICE_URL}/quarantine/{item['quarantine_id']}/cooldown",
            headers=auth_headers,
        )
        cooldown = cooldown_resp.json() if cooldown_resp.status_code == 200 else {}
        result.append({**item, "cooldown": cooldown})

    return jsonify(result), 200


@bp.route("/quarantine/<quarantine_id>/release", methods=["POST"])
def release_quarantine(quarantine_id):
    """Release a quarantine hold once its cooldown has expired.
    Releasing the post despite the hold means the user went against Trace's advice, so this resolves every detection that caused the hold (exposure_score >= 4) as "rejected".
    ---
    tags:
      - Quarantine
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: quarantine_id
        type: string
        required: true
    responses:
      200:
        description: Quarantine item released (state set to accepted).
        schema:
          $ref: "#/definitions/QuarantineItem"
      403:
        description: The cooldown period has not expired yet. Response body includes seconds_remaining.
      404:
        description: No quarantine item with that id exists.
      502:
        description: Failed to fetch the quarantine item, failed to fetch its cooldown status, or failed to apply the release.
    """
    auth_headers = forwarded_auth_headers(request)
    q_resp = requests.get(f"{QUARANTINE_ITEMS_SERVICE_URL}/quarantine/{quarantine_id}", headers=auth_headers)
    if q_resp.status_code == 404:
        return jsonify({"error": "quarantine item not found"}), 404
    if q_resp.status_code != 200:
        return jsonify({"error": "failed to fetch quarantine item"}), 502
    draft_id = q_resp.json()["draft_id"]

    # check cooldown before allowing release
    cooldown_resp = requests.get(
        f"{QUARANTINE_ITEMS_SERVICE_URL}/quarantine/{quarantine_id}/cooldown",
        headers=auth_headers,
    )
    if cooldown_resp.status_code != 200:
        return jsonify({"error": "failed to fetch cooldown status"}), 502

    cooldown = cooldown_resp.json()
    if not cooldown.get("expired"):
        return jsonify({
            "error": "cooldown has not expired",
            "seconds_remaining": cooldown.get("seconds_remaining"),
        }), 403

    patch_resp = requests.patch(
        f"{QUARANTINE_ITEMS_SERVICE_URL}/quarantine/{quarantine_id}",
        json={"state": "accepted"},
        headers=auth_headers,
    )
    if patch_resp.status_code != 200:
        return jsonify({"error": "failed to release quarantine item"}), 502

    # "Accepted"/"rejected" track whether the user went along with Trace's
    # advice, not whether the exposure physically went out — releasing a
    # post despite the warning means the user rejected that advice, so this
    # (not the edit-and-fix path) is what maps to "rejected".
    _set_high_risk_resolutions(draft_id, "rejected", auth_headers)

    return jsonify(patch_resp.json()), 200


@bp.route("/quarantine/<quarantine_id>/edit", methods=["POST"])
def edit_quarantine(quarantine_id):
    """Hand a quarantined draft off to remediation and mark the hold edited.
    Calls remediate_content to propose fixes for the draft's detections, then marks the quarantine item's state as edited.
    ---
    tags:
      - Quarantine
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: quarantine_id
        type: string
        required: true
    responses:
      200:
        description: Quarantine item marked edited, with the remediation result.
        schema:
          type: object
          properties:
            quarantine_item:
              $ref: "#/definitions/QuarantineItem"
            remediation:
              type: object
              properties:
                draft_id:
                  type: string
                original:
                  type: string
                  description: Path to the original file, or null if there was nothing to blur.
                proposed_edits:
                  type: array
                  items:
                    type: object
                text_redaction:
                  type: object
                  description: Suggested caption redaction, or null if there were no text-based detections.
      404:
        description: No quarantine item with that id exists.
      502:
        description: Failed to fetch the quarantine item, the remediation call failed, or updating the quarantine item's state failed.
    """
    auth_headers = forwarded_auth_headers(request)
    # fetch the quarantine item to get the draft_id
    q_resp = requests.get(f"{QUARANTINE_ITEMS_SERVICE_URL}/quarantine/{quarantine_id}", headers=auth_headers)
    if q_resp.status_code == 404:
        return jsonify({"error": "quarantine item not found"}), 404
    if q_resp.status_code != 200:
        return jsonify({"error": "failed to fetch quarantine item"}), 502

    draft_id = q_resp.json()["draft_id"]

    # hand off to remediate_content
    remediate_resp = requests.post(
        f"{REMEDIATE_CONTENT_SERVICE_URL}/drafts/{draft_id}/remediate",
        headers=auth_headers,
    )
    if remediate_resp.status_code != 200:
        return jsonify({"error": "remediation failed", "detail": remediate_resp.json()}), 502

    # mark quarantine item as edited
    patch_resp = requests.patch(
        f"{QUARANTINE_ITEMS_SERVICE_URL}/quarantine/{quarantine_id}",
        json={"state": "edited"},
        headers=auth_headers,
    )
    if patch_resp.status_code != 200:
        return jsonify({"error": "failed to update quarantine state"}), 502

    return jsonify({
        "quarantine_item": patch_resp.json(),
        "remediation": remediate_resp.json(),
    }), 200


@bp.route("/quarantine/<quarantine_id>/delete", methods=["POST"])
def delete_quarantine(quarantine_id):
    """Discard a quarantined draft without posting it.
    The flagged content never went out, so this resolves every detection that caused the hold (exposure_score >= 4) as "rejected".
    ---
    tags:
      - Quarantine
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: quarantine_id
        type: string
        required: true
    responses:
      200:
        description: Quarantine item discarded (state set to deleted).
        schema:
          $ref: "#/definitions/QuarantineItem"
      404:
        description: No quarantine item with that id exists.
      502:
        description: Failed to fetch the quarantine item, or failed to apply the delete.
    """
    auth_headers = forwarded_auth_headers(request)
    q_resp = requests.get(f"{QUARANTINE_ITEMS_SERVICE_URL}/quarantine/{quarantine_id}", headers=auth_headers)
    if q_resp.status_code == 404:
        return jsonify({"error": "quarantine item not found"}), 404
    if q_resp.status_code != 200:
        return jsonify({"error": "failed to fetch quarantine item"}), 502
    draft_id = q_resp.json()["draft_id"]

    patch_resp = requests.patch(
        f"{QUARANTINE_ITEMS_SERVICE_URL}/quarantine/{quarantine_id}",
        json={"state": "deleted"},
        headers=auth_headers,
    )
    if patch_resp.status_code != 200:
        return jsonify({"error": "failed to delete quarantine item"}), 502

    # the post itself was discarded rather than shared — the flagged risk
    # never went out.
    _set_high_risk_resolutions(draft_id, "rejected", auth_headers)

    return jsonify(patch_resp.json()), 200


# In professional setups, a Load Balancer and/or caller pings this /health URL every few seconds.
# If your code gets stuck in an infinite loop during a request,
# it will stop responding to /health.
@bp.get("/health")
def health():
    """Liveness check.
    Unauthenticated — polled frequently by the container orchestrator, so it must respond even while downstream services are unreachable.
    ---
    tags:
      - Health
    responses:
      200:
        description: The service process is alive.
    """
    return jsonify({"status": "ok"}), 200
