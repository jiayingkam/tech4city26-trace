import os
import requests
from flask import Blueprint, jsonify, request

from .extraction import extract_observations
from .inference import compute_delta

bp = Blueprint("detect_mosaic_risk", __name__)

CONTENT_DRAFTS_SERVICE_URL = os.environ.get("CONTENT_DRAFTS_SERVICE_URL", "http://CONTENT_DRAFTS:5002")
DETECTIONS_SERVICE_URL = os.environ.get("DETECTIONS_SERVICE_URL", "http://DETECTIONS:5003")


def _get_prior_detections(owner_id: str, exclude_draft_id: str) -> list[dict]:
    """Return all detection records from every prior post by this user, excluding the current draft."""
    drafts_resp = requests.get(f"{CONTENT_DRAFTS_SERVICE_URL}/users/{owner_id}/drafts")
    if drafts_resp.status_code != 200:
        return []

    detections = []
    for draft in drafts_resp.json():
        if draft["draft_id"] == exclude_draft_id:
            continue
        det_resp = requests.get(f"{DETECTIONS_SERVICE_URL}/drafts/{draft['draft_id']}/detections")
        if det_resp.status_code == 200:
            detections.extend(det_resp.json())
    return detections


def _get_draft_detections(draft_id: str) -> list[dict]:
    """Return detection records already recorded for the current draft (from scan_draft)."""
    resp = requests.get(f"{DETECTIONS_SERVICE_URL}/drafts/{draft_id}/detections")
    return resp.json() if resp.status_code == 200 else []


@bp.post("/users/<owner_id>/mosaic-risk")
def check_mosaic_risk(owner_id):
    """
    ---
    tags:
      - mosaic
    summary: Analyse cumulative disclosure risk for a draft against the user's post history.
    description: >
      Extracts typed observations from the draft's text, combines them with any image
      detections already recorded for the draft, and estimates how much this post narrows
      the author's anonymity set relative to their existing posts.
    parameters:
      - in: path
        name: owner_id
        required: true
        type: string
        description: UUID of the post owner.
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [draft_id]
          properties:
            draft_id:
              type: string
              description: UUID of the draft to analyse.
    responses:
      200:
        description: Risk assessment with anonymity delta and per-observation attribution.
      400:
        description: draft_id missing from request body.
      403:
        description: Draft does not belong to this owner.
      404:
        description: Draft not found.
      502:
        description: Upstream service error.
    """
    body = request.get_json(silent=True) or {}
    draft_id = body.get("draft_id")
    if not draft_id:
        return jsonify({"error": "draft_id is required"}), 400

    draft_resp = requests.get(f"{CONTENT_DRAFTS_SERVICE_URL}/drafts/{draft_id}")
    if draft_resp.status_code == 404:
        return jsonify({"error": "draft not found"}), 404
    if draft_resp.status_code != 200:
        return jsonify({"error": "failed to fetch draft"}), 502
    draft = draft_resp.json()

    if draft.get("owner_id") != owner_id:
        return jsonify({"error": "draft does not belong to this user"}), 403

    # Layer 1 — extract typed observations from the draft's text caption
    text_observations = extract_observations(draft.get("text_content") or "")

    # Also pick up any image detections already recorded by scan_draft for this draft
    new_draft_detections = _get_draft_detections(draft_id)

    if not text_observations and not new_draft_detections:
        return jsonify({
            "draft_id": draft_id,
            "owner_id": owner_id,
            "risk_level": "none",
            "message": "no locating observations found in this draft",
            "observations": [],
            "prior_post_count": 0,
            "k_before": None,
            "k_after": None,
            "delta_bits": 0.0,
            "top_contributors": [],
        }), 200

    # Gather all prior detections for this user (Layers 2 + 3 — history context)
    prior_detections = _get_prior_detections(owner_id, exclude_draft_id=draft_id)

    # Count how many distinct prior posts contributed
    prior_draft_ids = {d["draft_id"] for d in prior_detections}

    # Layer 3 + 4 — constraint intersection and anonymity delta
    delta = compute_delta(prior_detections, text_observations, new_draft_detections)

    return jsonify({
        "draft_id": draft_id,
        "owner_id": owner_id,
        "observations": [obs.model_dump() for obs in text_observations],
        "prior_post_count": len(prior_draft_ids),
        **delta,
    }), 200


@bp.get("/health")
def health():
    return jsonify({"status": "ok"}), 200
