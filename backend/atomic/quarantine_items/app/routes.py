from flask import Blueprint, jsonify
from .db import db
from .models import QuarantineItem

bp = Blueprint("quarantine_items", __name__)

from flask import Blueprint, request, jsonify
from datetime import datetime, timezone, timedelta

quarantine_bp = Blueprint("quarantine", __name__)

DEFAULT_COOLDOWN_MINUTES = 15

@quarantine_bp.route("/quarantine", methods=["POST"])
def create_quarantine():
    data = request.get_json()
    minutes = data.get("cooldown_minutes", DEFAULT_COOLDOWN_MINUTES)
    item = QuarantineItem(
        draft_id=data["draft_id"],
        reason=data["reason"],
        cooldown_expiry=datetime.now(timezone.utc) + timedelta(minutes=minutes),
    )
    db.session.add(item)
    db.session.commit()
    return jsonify(item.to_dict()), 201


@quarantine_bp.route("/drafts/<draft_id>/quarantine", methods=["GET"])
def list_quarantine(draft_id):
    # No extra sqlalchemy import needed if you use db.select!
    stmt = db.select(QuarantineItem).filter_by(draft_id=draft_id)
    items = db.session.scalars(stmt).all()
    return jsonify([i.to_dict() for i in items]), 200


@quarantine_bp.route("/quarantine/<quarantine_id>", methods=["GET"])
def get_quarantine(quarantine_id):
    item = db.session.get(QuarantineItem, quarantine_id)
    if item is None:
        return jsonify({"error": "quarantine item not found"}), 404
    return jsonify(item.to_dict()), 200


@quarantine_bp.route("/quarantine/<quarantine_id>/cooldown", methods=["GET"])
def cooldown_status(quarantine_id):
    item = db.session.get(QuarantineItem, quarantine_id)
    if item is None:
        return jsonify({"error": "quarantine item not found"}), 404
    now = datetime.now(timezone.utc)
    remaining = (item.cooldown_expiry - now).total_seconds()
    return jsonify({
        "quarantine_id": item.quarantine_id,
        "expired": remaining <= 0,
        "seconds_remaining": max(0, int(remaining)),
    }), 200


@quarantine_bp.route("/quarantine/<quarantine_id>", methods=["PATCH"])
def update_quarantine(quarantine_id):
    item = db.session.get(QuarantineItem, quarantine_id)
    if item is None:
        return jsonify({"error": "quarantine item not found"}), 404
    data = request.get_json()
    new_state = data.get("state")
    if new_state not in ("held", "released", "edited", "deleted"):
        return jsonify({"error": "invalid state"}), 400
    item.state = new_state
    db.session.commit()
    return jsonify(item.to_dict()), 200


@quarantine_bp.route("/quarantine/<quarantine_id>", methods=["DELETE"])
def delete_quarantine(quarantine_id):
    item = db.session.get(QuarantineItem, quarantine_id)
    if item is None:
        return jsonify({"error": "quarantine item not found"}), 404
    db.session.delete(item)
    db.session.commit()
    return "", 204


# In professional setups, a Load Balancer and/or caller pings this /health URL every few seconds.
# If your code gets stuck in an infinite loop while scraping Reddit,
# it will stop responding to /health.
@bp.get("/health")
def health():
    return jsonify({"status": "ok"}), 200
