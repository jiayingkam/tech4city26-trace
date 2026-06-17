import os
import requests
from flask import Blueprint, jsonify

bp = Blueprint("scan_draft", __name__)

DETECTIONS_SERVICE_URL = os.environ.get("DETECTIONS_SERVICE_URL", "http://DETECTIONS:5003")
QUARANTINE_HIGH_RISK_SERVICE_URL = os.environ.get("QUARANTINE_HIGH_RISK_SERVICE_URL", "http://QUARANTINE_HIGH_RISK:5010")
REMEDIATE_CONTENT_SERVICE_URL = os.environ.get("REMEDIATE_CONTENT_SERVICE_URL", "http://REMEDIATE_CONTENT:5011")


@bp.route("/drafts/<draft_id>/process", methods=["POST"])
def process_draft(draft_id):
    # fetch detections once; routing decision is based on the worst score present
    resp = requests.get(f"{DETECTIONS_SERVICE_URL}/drafts/{draft_id}/detections")
    if resp.status_code != 200:
        return jsonify({"error": "failed to fetch detections"}), 502
    detections = resp.json()
    if not detections:
        return jsonify({"error": "no detections found for this draft"}), 400

    # any region at score >=4 puts the whole draft on hold for human review
    if any(d["exposure_score"] >= 4 for d in detections):
        q_resp = requests.post(
            f"{QUARANTINE_HIGH_RISK_SERVICE_URL}/drafts/{draft_id}/quarantine"
        )
        if q_resp.status_code != 201:
            return jsonify({"error": "quarantine failed", "detail": q_resp.json()}), 502
        return jsonify({
            "draft_id": draft_id,
            "outcome": "quarantined",
            "quarantine": q_resp.json(),
        }), 201

    # all scores <=3 — safe to auto-remediate
    r_resp = requests.post(
        f"{REMEDIATE_CONTENT_SERVICE_URL}/drafts/{draft_id}/remediate"
    )
    if r_resp.status_code != 200:
        return jsonify({"error": "remediation failed", "detail": r_resp.json()}), 502
    return jsonify({
        "draft_id": draft_id,
        "outcome": "remediated",
        "remediation": r_resp.json(),
    }), 200


# In professional setups, a Load Balancer and/or caller pings this /health URL every few seconds.
# If your code gets stuck in an infinite loop during a request,
# it will stop responding to /health.
@bp.get("/health")
def health():
    return jsonify({"status": "ok"}), 200
