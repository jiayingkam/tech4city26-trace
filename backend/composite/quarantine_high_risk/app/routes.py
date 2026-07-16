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

    # posted as-is despite the warning — the flagged risk went out uncorrected.
    _set_high_risk_resolutions(draft_id, "accepted", auth_headers)

    return jsonify(patch_resp.json()), 200


@bp.route("/quarantine/<quarantine_id>/edit", methods=["POST"])
def edit_quarantine(quarantine_id):
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
    return jsonify({"status": "ok"}), 200
