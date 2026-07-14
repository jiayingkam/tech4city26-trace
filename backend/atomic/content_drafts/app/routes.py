from flask import Blueprint, request, jsonify
from .db import db
from .models import ContentDrafts

bp = Blueprint("content_drafts", __name__)

VALID_CONTENT_TYPES = ("text", "image", "video")


def _json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, (jsonify({"error": "request body must be a JSON object"}), 400)
    return data, None


def _missing_required(data, fields):
    missing = [field for field in fields if data.get(field) in (None, "")]
    if missing:
        return jsonify({"error": "missing required field(s)", "fields": missing}), 400
    return None


@bp.route("/drafts", methods=["POST"])
def create_draft():
    data, error = _json_body()
    if error:
        return error
    error = _missing_required(data, ("owner_id", "content_type"))
    if error:
        return error
    if data["content_type"] not in VALID_CONTENT_TYPES:
        return jsonify({"error": "invalid content_type"}), 400
    draft = ContentDrafts(
        owner_id=data["owner_id"],
        content_type=data["content_type"],
        source_app=data.get("source_app"),
        storage_path=data.get("storage_path"),
        text_content=data.get("text_content"),
    )
    db.session.add(draft)
    db.session.commit()
    return jsonify(draft.to_dict()), 201


@bp.route("/drafts/<draft_id>", methods=["GET"])
def get_draft(draft_id):
    draft = db.session.get(ContentDrafts, draft_id)
    if draft is None:
        return jsonify({"error": "draft not found"}), 404
    return jsonify(draft.to_dict()), 200


@bp.route("/users/<owner_id>/drafts", methods=["GET"])
def list_drafts_for_owner(owner_id):
    stmt = db.select(ContentDrafts).filter_by(owner_id=owner_id)
    drafts = db.session.scalars(stmt).all()
    return jsonify([d.to_dict() for d in drafts]), 200


@bp.route("/drafts/<draft_id>", methods=["DELETE"])
def delete_draft(draft_id):
    draft = db.session.get(ContentDrafts, draft_id)
    if draft is None:
        return jsonify({"error": "draft not found"}), 404
    db.session.delete(draft)
    db.session.commit()
    return "", 204


# In professional setups, a Load Balancer and/or caller pings this /health URL every few seconds.
# If your code gets stuck in an infinite loop during a request,
# it will stop responding to /health.
@bp.get("/health")
def health():
    return jsonify({"status": "ok"}), 200