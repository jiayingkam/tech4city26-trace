import logging
import os
import re
import requests

_log = logging.getLogger(__name__)
from flask import Blueprint, jsonify, request

from .extraction import Observation, extract_observations
from .inference import K_BASELINE, _bits_to_k, compute_delta


bp = Blueprint("detect_mosaic_risk", __name__)

CONTENT_DRAFTS_SERVICE_URL = os.environ.get("CONTENT_DRAFTS_SERVICE_URL", "http://CONTENT_DRAFTS:5002")
DETECTIONS_SERVICE_URL = os.environ.get("DETECTIONS_SERVICE_URL", "http://DETECTIONS:5003")

# Maps detection category → (Observation.kind, Observation.target)
_CATEGORY_KIND_TARGET: dict[str, tuple[str, str]] = {
    "location":    ("location",    "routine"),
    "metadata":    ("location",    "home"),
    "document":    ("affiliation", "identity"),
    "contact":     ("relation",    "network"),
    "financial":   ("possession",  "identity"),
    "credentials": ("possession",  "identity"),
}

# Words in detail that signal the scanner is hedging — uncertain about what it found
_HEDGE_WORDS = (
    "may ", "could ", "might ", "likely ", "appears ", "appears to",
    "possible", "possibly", "unclear", "too unclear",
)

# Proper-noun-looking words that are NOT concrete identifiers (common in scanner descriptions)
_GENERIC_CAPS = {
    "This", "The", "A", "An", "No", "School", "GPS", "OCR",
    "Possible", "Unclear", "Sign", "Badge", "Crest", "Photo",
}


def _has_concrete_content(detail: str) -> bool:
    """True if detail contains an actual extracted value from the image.

    Accepts: any digit (address, number, plate), quoted text, or a proper noun
    that isn't a generic scanner word — indicating the scanner named a real entity.
    """
    if re.search(r"\d", detail):
        return True
    if re.search(r'["\']', detail):
        return True
    words = detail.split()
    return any(
        w and w[0].isupper() and w.rstrip(".,") not in _GENERIC_CAPS
        for w in words[1:]  # skip first word — always capitalised in a sentence
        if w and w[0].isalpha()
    )


def _auth_headers() -> dict:
    auth = request.headers.get("Authorization")
    return {"Authorization": auth} if auth else {}


def _is_vague(det: dict) -> bool:
    """True when the detection carries no concrete extracted content.

    Three conditions, checked in order:
    1. model_version contains 'unclear' — OCR path that couldn't read the text.
    2. detail contains hedging words — scanner is uncertain about what it found.
    3. No concrete anchor in detail (digit / quoted text / proper entity name) AND
       not EXIF — EXIF always carries concrete data (GPS present) even without
       printing the coordinates in the description.
    """
    model_version = det.get("model_version") or ""
    if "unclear" in model_version:
        return True

    detail = det.get("detail") or ""
    detail_lower = detail.lower()
    if any(h in detail_lower for h in _HEDGE_WORDS):
        return True

    # EXIF scanner: GPS presence is itself the concrete fact — no further check needed
    if model_version == "exif-parser-1.0":
        return False

    return not _has_concrete_content(detail)


def _detection_bits(det: dict) -> float:
    """0 for vague findings; otherwise exposure_score * 0.5, capped at 5."""
    if _is_vague(det):
        return 0.0
    return min(det.get("exposure_score", 1) * 0.5, 5.0)


def _word_jaccard(a: str, b: str) -> float:
    wa, wb = set(a.lower().split()), set(b.lower().split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _dedup_observations(obs_list: list[Observation]) -> list[Observation]:
    """Drop near-duplicate observations (Jaccard > 0.7 on constraint words)."""
    kept: list[Observation] = []
    for obs in obs_list:
        if not any(_word_jaccard(obs.constraint, k.constraint) > 0.7 for k in kept):
            kept.append(obs)
    return kept


def _detection_to_observation(det: dict) -> Observation:
    """Convert an image detection record into a typed Observation.

    Vague detections (unclear signage, low-confidence guesses) get 0 bits so
    they appear in the response for transparency but don't move k.
    Kind/target are derived from the detection category, not hardcoded to
    possession/identity.
    """
    category = det.get("category", "unknown")
    kind, target = _CATEGORY_KIND_TARGET.get(category, ("possession", "identity"))
    detail = det.get("detail") or category
    return Observation(
        kind=kind,
        target=target,
        surface=detail,
        entity=None,
        constraint=f"{category}: {detail}",
        contribution_bits=_detection_bits(det),
    )


def _observations_for_draft(draft: dict, detections: list[dict]) -> list[Observation]:
    """Extract all observations for one draft: caption text + image detections combined.

    Always processes both sources so caption observations are never silently dropped
    when scan_draft also found something in the image.
    """
    text_obs = extract_observations(draft.get("text_content") or "")
    image_obs = _dedup_observations([
        _detection_to_observation(d) for d in detections if d.get("detail")
    ])
    return text_obs + image_obs


def _get_prior_observations(owner_id: str, exclude_draft_id: str) -> list[Observation]:
    """Build Observation list from every prior post by this user."""
    headers = _auth_headers()
    drafts_resp = requests.get(
        f"{CONTENT_DRAFTS_SERVICE_URL}/users/{owner_id}/drafts", headers=headers
    )
    if drafts_resp.status_code != 200:
        return []

    observations: list[Observation] = []
    for draft in drafts_resp.json():
        if draft["draft_id"] == exclude_draft_id:
            continue

        det_resp = requests.get(
            f"{DETECTIONS_SERVICE_URL}/drafts/{draft['draft_id']}/detections",
            headers=headers,
        )
        detections = det_resp.json() if det_resp.status_code == 200 else []
        observations += _observations_for_draft(draft, detections)

    return observations


def _get_draft_detections(draft_id: str) -> list[dict]:
    """Return detection records already recorded for the current draft (from scan_draft)."""
    resp = requests.get(
        f"{DETECTIONS_SERVICE_URL}/drafts/{draft_id}/detections", headers=_auth_headers()
    )
    return resp.json() if resp.status_code == 200 else []


@bp.post("/users/<owner_id>/mosaic-risk")
def check_mosaic_risk(owner_id):
    """Analyse cumulative disclosure risk for a draft against the user's post history.
    ---
    tags:
      - Mosaic Risk
    security:
      - BearerAuth: []
    consumes:
      - application/json
    parameters:
      - in: path
        name: owner_id
        type: string
        required: true
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - draft_id
          properties:
            draft_id:
              type: string
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

    headers = _auth_headers()
    draft_resp = requests.get(
        f"{CONTENT_DRAFTS_SERVICE_URL}/drafts/{draft_id}", headers=headers
    )
    if draft_resp.status_code == 404:
        return jsonify({"error": "draft not found"}), 404
    if draft_resp.status_code != 200:
        return jsonify({"error": "failed to fetch draft"}), 502
    draft = draft_resp.json()

    if draft.get("owner_id") != owner_id:
        return jsonify({"error": "draft does not belong to this user"}), 403

    # Layer 1 — extract typed observations from the draft's text caption
    text_observations = extract_observations(draft.get("text_content") or "")

    # Convert image detections (from scan_draft) to Observation objects so every
    # bit that moves k is represented in the observations list — enforces the
    # invariant delta_bits == sum(obs.contribution_bits for obs in observations).
    # Vague detections get 0 bits; near-duplicates from the same image are deduped.
    raw_detections = _get_draft_detections(draft_id)
    image_observations = _dedup_observations([
        _detection_to_observation(d) for d in raw_detections if d.get("detail")
    ])
    all_new_observations = text_observations + image_observations

    # Always compute prior observations — needed for k_before even on empty drafts
    prior_observations = _get_prior_observations(owner_id, exclude_draft_id=draft_id)
    prior_bits = sum((obs.contribution_bits or 0.0) for obs in prior_observations)
    k_from_history = _bits_to_k(prior_bits)

    if not all_new_observations:
        return jsonify({
            "draft_id": draft_id,
            "owner_id": owner_id,
            "risk_level": "none",
            "message": "no locating observations found in this draft",
            "observations": [],
            "prior_constraint_count": len(prior_observations),
            "k_before": k_from_history,
            "k_after": k_from_history,
            "delta_bits": 0.0,
            "top_contributors": [],
        }), 200

    delta = compute_delta(prior_observations, all_new_observations)

    return jsonify({
        "draft_id": draft_id,
        "owner_id": owner_id,
        "observations": [obs.model_dump() for obs in all_new_observations],
        "prior_constraint_count": len(prior_observations),
        **delta,
    }), 200


@bp.get("/users/<owner_id>/mosaic-trajectory")
def mosaic_trajectory(owner_id):
    """Replay all posts for a user in timestamp order and return k after each post.
    Useful for visualising how the anonymity set narrows across the posting history.
    ---
    tags:
      - Mosaic Risk
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: owner_id
        type: string
        required: true
    responses:
      200:
        description: Ordered list of k values, one per post.
      502:
        description: Upstream service error.
    """
    headers = _auth_headers()
    drafts_resp = requests.get(
        f"{CONTENT_DRAFTS_SERVICE_URL}/users/{owner_id}/drafts", headers=headers
    )
    if drafts_resp.status_code != 200:
        return jsonify({"error": "failed to fetch drafts"}), 502

    drafts = sorted(drafts_resp.json(), key=lambda d: d.get("captured_at", ""))

    trajectory = []
    accumulated_bits = 0.0

    for draft in drafts:
        det_resp = requests.get(
            f"{DETECTIONS_SERVICE_URL}/drafts/{draft['draft_id']}/detections",
            headers=headers,
        )
        detections = det_resp.json() if det_resp.status_code == 200 else []

        post_observations = _observations_for_draft(draft, detections)

        for obs in post_observations:
            _log.debug(
                "trajectory draft=%s obs=%r bits=%.2f",
                draft["draft_id"], obs.constraint, obs.contribution_bits or 0.0,
            )

        post_bits = sum((obs.contribution_bits or 0.0) for obs in post_observations)
        k_before = _bits_to_k(accumulated_bits)
        accumulated_bits += post_bits
        k_after = _bits_to_k(accumulated_bits)
        delta_bits = round(post_bits, 2)

        if k_after <= 1_000:
            risk_level = "high"
        elif k_after <= 10_000:
            risk_level = "medium"
        else:
            risk_level = "low"

        trajectory.append({
            "draft_id": draft["draft_id"],
            "text_content": draft.get("text_content", ""),
            "captured_at": draft.get("captured_at"),
            "observation_count": len(post_observations),
            "k_before": k_before,
            "k_after": k_after,
            "delta_bits": round(post_bits, 2),
            "risk_level": risk_level,
        })

    return jsonify({
        "owner_id": owner_id,
        "post_count": len(trajectory),
        "final_k": _bits_to_k(accumulated_bits),
        "trajectory": trajectory,
    }), 200


@bp.get("/health")
def health():
    """Liveness check.
    ---
    tags:
      - Health
    responses:
      200:
        description: The service process is alive.
    """
    return jsonify({"status": "ok"}), 200
