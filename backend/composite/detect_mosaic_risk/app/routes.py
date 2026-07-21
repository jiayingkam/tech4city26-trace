import logging
import os
import re
from collections import Counter

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

# Fraction of bits retained after a user accepts a cleanup fix (blur/strip).
# Blurring reduces contextual signal significantly but the surrounding scene still leaks.
_CLEANUP_RESIDUAL = 0.15

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
    Detections where the user accepted the fix (resolution=accepted) also get
    0 bits — the harmful content was removed before posting.
    Kind/target are derived from the detection category, not hardcoded to
    possession/identity.
    """
    category = det.get("category", "unknown")
    kind, target = _CATEGORY_KIND_TARGET.get(category, ("possession", "identity"))
    detail = det.get("detail") or category
    raw_bits = _detection_bits(det)
    bits = raw_bits * _CLEANUP_RESIDUAL if det.get("resolution") == "accepted" else raw_bits
    return Observation(
        kind=kind,
        target=target,
        surface=detail,
        entity=None,
        constraint=f"{category}: {detail}",
        contribution_bits=bits,
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

        # A post is published if all detections are resolved AND at least one was
        # accepted (user confirmed the remediation flow). Posts where every
        # detection is rejected are cancellations — never published.
        all_resolved = not any(d.get("resolution") is None for d in detections)
        any_accepted = any(d.get("resolution") == "accepted" for d in detections)
        if not all_resolved or (detections and not any_accepted):
            continue

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


def _behavior_factor(trajectory: list[dict]) -> dict:
    """Score how much a user relies on app cleanup vs. naturally posting clean content.

    Compares cleanup_reliance (fraction of image-detection bits saved by accepting fixes)
    across the first and second halves of the post history. Improving over time gets full
    credit; consistently high reliance with no trend reduces the factor.

    Returns behavior_factor (0.70–1.00), behavior_label, and behavior_penalty_pts.
    """
    with_images = [p for p in trajectory if p.get("raw_image_bits", 0) > 0]

    if len(with_images) == 0:
        # All images were clean — no risky content detected in any post.
        return {"behavior_factor": 1.0, "behavior_label": "clean", "behavior_penalty_pts": 0}

    if len(with_images) < 3:
        # Too few image-detection posts for a trend — judge on overall reliance alone.
        avg = sum(p["cleanup_reliance"] for p in with_images) / len(with_images)
        if avg < 0.3:
            return {"behavior_factor": 1.0, "behavior_label": "clean", "behavior_penalty_pts": 0}
        if avg < 0.6:
            return {"behavior_factor": 0.90, "behavior_label": "steady", "behavior_penalty_pts": 0}
        return {"behavior_factor": 0.80, "behavior_label": "reliant", "behavior_penalty_pts": 0}

    def avg_reliance(pts):
        return sum(p["cleanup_reliance"] for p in pts) / len(pts)

    mid = len(with_images) // 2
    early_avg = avg_reliance(with_images[:mid])
    recent_avg = avg_reliance(with_images[mid:])
    overall_avg = avg_reliance(with_images)
    improvement = early_avg - recent_avg  # positive = getting cleaner over time

    if overall_avg < 0.2:
        # Rarely needs cleanup — naturally clean poster.
        factor, label = 1.0, "clean"
    elif improvement > 0.25:
        # Meaningfully improving: posts are getting cleaner over time.
        factor, label = 0.93, "improving"
    elif improvement > 0.05 or overall_avg < 0.5:
        # Slight improvement or moderate reliance — give benefit of the doubt.
        factor, label = 0.85, "steady"
    else:
        # High reliance, no improvement trend — user is not learning.
        factor = max(0.70, 1.0 - overall_avg * 0.35)
        label = "reliant"

    return {
        "behavior_factor": round(factor, 2),
        "behavior_label": label,
        "behavior_penalty_pts": 0,  # frontend computes displayed score as score * factor
    }


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
    saves = []
    accumulated_bits = 0.0
    saved_bits_total = 0.0
    overall_type_counts: Counter = Counter()

    for draft in drafts:
        det_resp = requests.get(
            f"{DETECTIONS_SERVICE_URL}/drafts/{draft['draft_id']}/detections",
            headers=headers,
        )
        detections = det_resp.json() if det_resp.status_code == 200 else []

        all_resolved = not any(d.get("resolution") is None for d in detections)
        any_accepted = any(d.get("resolution") == "accepted" for d in detections)

        # Pending — still awaiting user decision, skip entirely.
        if not all_resolved:
            continue

        # All detections rejected = user cancelled/chose not to post.
        # Record as a privacy save: compute the bits that would have been exposed.
        if detections and not any_accepted:
            # Use _detection_bits directly (ignoring resolution) for would-be impact.
            would_be_bits = sum(
                _detection_bits(d) for d in detections if d.get("detail")
            )
            if would_be_bits > 0:
                saves.append({
                    "draft_id": draft["draft_id"],
                    "text_content": draft.get("text_content", ""),
                    "captured_at": draft.get("captured_at"),
                    "would_be_delta_bits": round(would_be_bits, 2),
                })
                saved_bits_total += would_be_bits
            continue

        # Published post (clean, or partially/fully remediated).
        # _detection_to_observation already gives residual bits to accepted detections.
        image_detections = [d for d in detections if d.get("detail")]
        text_obs = extract_observations(draft.get("text_content") or "")
        image_obs = _dedup_observations([_detection_to_observation(d) for d in image_detections])
        post_observations = text_obs + image_obs

        for obs in post_observations:
            _log.debug(
                "trajectory draft=%s obs=%r bits=%.2f",
                draft["draft_id"], obs.constraint, obs.contribution_bits or 0.0,
            )

        # raw_image_bits: what image detections would cost with no cleanup.
        # actual_image_bits: what they cost after applying cleanup residual.
        # cleanup_reliance: fraction of image exposure saved by the app (0 = no cleanup needed).
        raw_image_bits = sum(_detection_bits(d) for d in image_detections)
        actual_image_bits = sum((obs.contribution_bits or 0.0) for obs in image_obs)
        cleanup_reliance = (
            (raw_image_bits - actual_image_bits) / raw_image_bits
            if raw_image_bits > 0 else 0.0
        )

        post_bits = sum((obs.contribution_bits or 0.0) for obs in post_observations)
        k_before = _bits_to_k(accumulated_bits)
        accumulated_bits += post_bits
        k_after = _bits_to_k(accumulated_bits)

        if k_after <= 1_000:
            risk_level = "high"
        elif k_after <= 10_000:
            risk_level = "medium"
        else:
            risk_level = "low"

        kinds_this_post = {
            obs.kind for obs in post_observations if (obs.contribution_bits or 0.0) > 0
        }
        overall_type_counts.update(kinds_this_post)

        cleaned = any(d.get("resolution") == "accepted" for d in detections)

        trajectory.append({
            "draft_id": draft["draft_id"],
            "text_content": draft.get("text_content", ""),
            "captured_at": draft.get("captured_at"),
            "observation_count": len(post_observations),
            "k_before": k_before,
            "k_after": k_after,
            "delta_bits": round(post_bits, 2),
            "raw_image_bits": round(raw_image_bits, 2),
            "cleanup_reliance": round(cleanup_reliance, 3),
            "risk_level": risk_level,
            "cleaned": cleaned,
        })

    behavior = _behavior_factor(trajectory)

    return jsonify({
        "owner_id": owner_id,
        "post_count": len(trajectory),
        "final_k": _bits_to_k(accumulated_bits),
        "type_summary": dict(overall_type_counts),
        "trajectory": trajectory,
        "saves": saves,
        "saved_bits": round(saved_bits_total, 2),
        **behavior,
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
