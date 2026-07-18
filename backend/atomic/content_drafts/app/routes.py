from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
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
    """Create a content draft.
    Stores a new draft (text/image/video) for later scanning and remediation. owner_id must match the authenticated caller.
    ---
    tags:
      - Content Drafts
    security:
      - BearerAuth: []
    consumes:
      - application/json
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - owner_id
            - content_type
          properties:
            owner_id:
              type: string
              description: Must match the authenticated user's id.
            content_type:
              type: string
              enum: [text, image, video]
            source_app:
              type: string
              example: instagram
            storage_path:
              type: string
              description: Path/key to the raw file in storage. Omit for text-only drafts.
            text_content:
              type: string
              description: Caption/body text. Omit for image/video drafts.
    responses:
      201:
        description: Draft created.
        schema:
          id: ContentDraft
          type: object
          properties:
            draft_id:
              type: string
            owner_id:
              type: string
            content_type:
              type: string
            source_app:
              type: string
            storage_path:
              type: string
            text_content:
              type: string
            captured_at:
              type: string
              format: date-time
      400:
        description: Request body is not a JSON object, a required field is missing, or content_type is invalid.
      403:
        description: owner_id does not match the authenticated user.
    """
    data, error = _json_body()
    if error:
        return error
    error = _missing_required(data, ("owner_id", "content_type"))
    if error:
        return error
    if data["owner_id"] != get_jwt_identity():
        return jsonify({"error": "owner_id must match the authenticated user"}), 403
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
    """Get a content draft by id.
    ---
    tags:
      - Content Drafts
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: draft_id
        type: string
        required: true
    responses:
      200:
        description: The draft.
        schema:
          $ref: "#/definitions/ContentDraft"
      403:
        description: The draft belongs to a different user.
      404:
        description: No draft with that id exists.
    """
    draft = db.session.get(ContentDrafts, draft_id)
    if draft is None:
        return jsonify({"error": "draft not found"}), 404
    if draft.owner_id != get_jwt_identity():
        return jsonify({"error": "forbidden"}), 403
    return jsonify(draft.to_dict()), 200


@bp.route("/users/<owner_id>/drafts", methods=["GET"])
def list_drafts_for_owner(owner_id):
    """List all drafts owned by a user.
    ---
    tags:
      - Content Drafts
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: owner_id
        type: string
        required: true
    responses:
      200:
        description: The user's drafts, most recently created first is not guaranteed — callers should sort if order matters.
        schema:
          type: array
          items:
            $ref: "#/definitions/ContentDraft"
      403:
        description: owner_id does not match the authenticated user.
    """
    if owner_id != get_jwt_identity():
        return jsonify({"error": "forbidden"}), 403
    stmt = db.select(ContentDrafts).filter_by(owner_id=owner_id)
    drafts = db.session.scalars(stmt).all()
    return jsonify([d.to_dict() for d in drafts]), 200


@bp.route("/drafts/<draft_id>", methods=["PATCH"])
def update_draft(draft_id):
    """Update a draft's storage path and/or text content.
    Only storage_path and text_content are mutable — everything else about a draft is fixed at creation.
    ---
    tags:
      - Content Drafts
    security:
      - BearerAuth: []
    consumes:
      - application/json
    parameters:
      - in: path
        name: draft_id
        type: string
        required: true
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            storage_path:
              type: string
            text_content:
              type: string
    responses:
      200:
        description: The updated draft.
        schema:
          $ref: "#/definitions/ContentDraft"
      400:
        description: Request body is not a JSON object.
      403:
        description: The draft belongs to a different user.
      404:
        description: No draft with that id exists.
    """
    draft = db.session.get(ContentDrafts, draft_id)
    if draft is None:
        return jsonify({"error": "draft not found"}), 404
    if draft.owner_id != get_jwt_identity():
        return jsonify({"error": "forbidden"}), 403
    data, error = _json_body()
    if error:
        return error
    if "storage_path" in data:
        draft.storage_path = data["storage_path"]
    if "text_content" in data:
        draft.text_content = data["text_content"]
    db.session.commit()
    return jsonify(draft.to_dict()), 200


@bp.route("/drafts/<draft_id>", methods=["DELETE"])
def delete_draft(draft_id):
    """Delete a draft.
    ---
    tags:
      - Content Drafts
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: draft_id
        type: string
        required: true
    responses:
      204:
        description: Draft deleted.
      403:
        description: The draft belongs to a different user.
      404:
        description: No draft with that id exists.
    """
    draft = db.session.get(ContentDrafts, draft_id)
    if draft is None:
        return jsonify({"error": "draft not found"}), 404
    if draft.owner_id != get_jwt_identity():
        return jsonify({"error": "forbidden"}), 403
    db.session.delete(draft)
    db.session.commit()
    return "", 204


# In professional setups, a Load Balancer and/or caller pings this /health URL every few seconds.
# If your code gets stuck in an infinite loop during a request,
# it will stop responding to /health.
@bp.get("/health")
def health():
    """Liveness check.
    Unauthenticated — polled frequently by the container orchestrator, so it must respond even while the database is unreachable.
    ---
    tags:
      - Health
    responses:
      200:
        description: The service process is alive.
    """
    return jsonify({"status": "ok"}), 200