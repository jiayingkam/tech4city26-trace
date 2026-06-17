import os
import requests
from flask import Blueprint, jsonify, send_file
from PIL import Image, ImageFilter

remediate_bp = Blueprint("remediate_content", __name__)

DETECTIONS_SERVICE_URL = os.environ.get("DETECTIONS_SERVICE_URL", "http://DETECTIONS:5003")
EDITS_SERVICE_URL = os.environ.get("EDITS_SERVICE_URL", "http://EDITS:5004")

ORIGINAL_DIR = "storage/originals"
OUTPUT_DIR = "storage/remediated"

def apply_remediation(original_path, detections):
    """Blur each region that has a box, then strip metadata. Returns output path."""
    img = Image.open(original_path)

    for d in detections:
        region = d.get("bounding_region")
        if region:  # blur this box; metadata-only detections have no box
            box = (region["x"], region["y"],
                   region["x"] + region["w"], region["y"] + region["h"])
            blurred = img.crop(box).filter(ImageFilter.GaussianBlur(radius=15))
            img.paste(blurred, box)

    out_path = os.path.join(OUTPUT_DIR, os.path.basename(original_path))
    img.save(out_path)  # not passing exif= strips the GPS/EXIF on save
    return out_path


@remediate_bp.route("/drafts/<draft_id>/remediate", methods=["POST"])
def remediate_content(draft_id):
    # 1. fetch detections, low/medium risk only (>=4 is quarantine's job)
    resp = requests.get(f"{DETECTIONS_SERVICE_URL}/drafts/{draft_id}/detections")
    if resp.status_code != 200:
        return jsonify({"error": "failed to fetch detections"}), 502
    detections = [d for d in resp.json() if d["exposure_score"] <= 3]
    if not detections:
        return jsonify({"error": "nothing to remediate"}), 400

    # 2. locate the original (integration seam — see note below)
    original_path = os.path.join(ORIGINAL_DIR, f"{draft_id}.jpg")

    # 3. apply blur + strip
    output_path = apply_remediation(original_path, detections)

    # 4. write one pending edit per detection via edits service
    created = []
    for d in detections:
        payload = {
            "draft_id": draft_id,
            "edit_type": "blur" if d.get("bounding_region") else "metadata_strip",
            "region_affected": d.get("bounding_region"),
        }
        edit_resp = requests.post(f"{EDITS_SERVICE_URL}/edits", json=payload)
        if edit_resp.status_code != 201:
            return jsonify({"error": "failed to create edit"}), 502
        created.append(edit_resp.json())

    # 5. return side-by-side preview
    return jsonify({
        "draft_id": draft_id,
        "before": f"/{ORIGINAL_DIR}/{draft_id}.jpg",
        "after": f"/{OUTPUT_DIR}/{os.path.basename(output_path)}",
        "edits": created,
    }), 200


@remediate_bp.route("/drafts/<draft_id>/remediate/confirm", methods=["POST"])
def confirm_remediation(draft_id):
    resp = requests.get(f"{EDITS_SERVICE_URL}/drafts/{draft_id}/edits")
    if resp.status_code != 200:
        return jsonify({"error": "failed to fetch edits"}), 502
    pending = [e for e in resp.json() if e["status"] == "pending"]
    if not pending:
        return jsonify({"error": "no pending edits to confirm"}), 400
    confirmed = []
    for e in pending:
        patch_resp = requests.patch(f"{EDITS_SERVICE_URL}/edits/{e['edit_id']}", json={"status": "applied"})
        if patch_resp.status_code != 200:
            return jsonify({"error": "failed to update edit"}), 502
        confirmed.append(patch_resp.json())
    return jsonify({
        "draft_id": draft_id,
        "confirmed": confirmed,
        "download_url": f"/drafts/{draft_id}/download",
    }), 200

@remediate_bp.route("/drafts/<draft_id>/download", methods=["GET"])
def download_remediated(draft_id):
    # only serve the clean file if the user confirmed (>=1 applied edit)
    resp = requests.get(f"{EDITS_SERVICE_URL}/drafts/{draft_id}/edits")
    if resp.status_code != 200:
        return jsonify({"error": "failed to fetch edits"}), 502
    if not any(e["status"] == "applied" for e in resp.json()):
        return jsonify({"error": "no confirmed remediation for this draft"}), 400

    path = os.path.join(OUTPUT_DIR, f"{draft_id}.jpg")
    if not os.path.exists(path):
        return jsonify({"error": "remediated file not found"}), 404

    return send_file(path, as_attachment=True, download_name=f"trace_clean_{draft_id}.jpg")


@remediate_bp.route("/edits/<edit_id>/revert", methods=["POST"])
def revert_edit(edit_id):
    resp = requests.get(f"{EDITS_SERVICE_URL}/edits/{edit_id}")
    if resp.status_code == 404:
        return jsonify({"error": "edit not found"}), 404
    if resp.status_code != 200:
        return jsonify({"error": "failed to fetch edit"}), 502
    patch_resp = requests.patch(f"{EDITS_SERVICE_URL}/edits/{edit_id}", json={"status": "reverted"})
    if patch_resp.status_code != 200:
        return jsonify({"error": "failed to revert edit"}), 502
    return jsonify(patch_resp.json()), 200


# In professional setups, a Load Balancer and/or caller pings this /health URL every few seconds.
# If your code gets stuck in an infinite loop during a request,
# it will stop responding to /health.
@remediate_bp.get("/health")
def health():
    return jsonify({"status": "ok"}), 200
