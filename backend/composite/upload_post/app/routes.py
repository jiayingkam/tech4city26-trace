import os
import requests
from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import get_jwt_identity
from werkzeug.utils import secure_filename
from trace_auth import forwarded_auth_headers
import trace_storage

bp = Blueprint("upload_post", __name__)

CONTENT_DRAFTS_SERVICE_URL = os.environ.get("CONTENT_DRAFTS_SERVICE_URL", "http://CONTENT_DRAFTS:5002")

VALID_CONTENT_TYPES = ("text", "image", "video")
DEFAULT_EXTENSION = ".jpg"


def _safe_detail(resp):
    """Downstream errors aren't always JSON (a raw 500 from an unhandled
    exception is an HTML page) — .json() would raise and mask the real
    failure behind a second, unhandled crash in this service."""
    try:
        return resp.json()
    except ValueError:
        return resp.text[:500]


@bp.route("/drafts", methods=["POST"])
def upload_draft():
    """Create a content draft and upload its file.
    Creates a content_drafts record and, if a file was sent, writes it to the GCS bucket and attaches its storage_path to the draft. One call for the frontend to make on 'Share' — mirrors scan_draft/process, which also folds several atomic calls into a single composite endpoint.
    ---
    tags:
      - Upload Post
    security:
      - BearerAuth: []
    consumes:
      - multipart/form-data
    parameters:
      - in: formData
        name: content_type
        type: string
        required: true
        enum: [text, image, video]
      - in: formData
        name: source_app
        type: string
        required: false
        example: instagram
      - in: formData
        name: text_content
        type: string
        required: false
        description: Caption/body text.
      - in: formData
        name: file
        type: file
        required: false
        description: Required when content_type is image or video.
    responses:
      201:
        description: Draft created (and file stored, if one was sent).
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
        description: content_type is missing/invalid, or content_type is image/video but no file was sent.
      502:
        description: The content_drafts service failed to create/update the draft, or the file failed to upload to storage.
    """
    # owner_id comes from the caller's own token, not the form body — a
    # client can no longer create a draft on someone else's behalf just by
    # naming a different owner_id.
    owner_id = get_jwt_identity()
    content_type = request.form.get("content_type")
    source_app = request.form.get("source_app")
    text_content = request.form.get("text_content")
    file = request.files.get("file")
    auth_headers = forwarded_auth_headers(request)

    if content_type not in VALID_CONTENT_TYPES:
        return jsonify({"error": "a valid content_type is required"}), 400
    if content_type in ("image", "video") and file is None:
        return jsonify({"error": "file is required for content_type image/video"}), 400

    create_resp = requests.post(f"{CONTENT_DRAFTS_SERVICE_URL}/drafts", json={
        "owner_id": owner_id,
        "content_type": content_type,
        "source_app": source_app,
        "text_content": text_content,
    }, headers=auth_headers)
    if create_resp.status_code != 201:
        return jsonify({"error": "failed to create draft", "detail": _safe_detail(create_resp)}), 502
    draft = create_resp.json()
    draft_id = draft["draft_id"]

    if file is not None:
        ext = os.path.splitext(secure_filename(file.filename))[1].lower() or DEFAULT_EXTENSION
        relative_path = f"storage/originals/{draft_id}{ext}"

        try:
            trace_storage.upload_bytes(relative_path, file.read(), content_type=file.mimetype)
        except Exception as e:
            requests.delete(f"{CONTENT_DRAFTS_SERVICE_URL}/drafts/{draft_id}", headers=auth_headers)
            return jsonify({"error": "failed to store file", "detail": str(e)}), 502

        patch_resp = requests.patch(
            f"{CONTENT_DRAFTS_SERVICE_URL}/drafts/{draft_id}",
            json={"storage_path": relative_path},
            headers=auth_headers,
        )
        if patch_resp.status_code != 200:
            requests.delete(f"{CONTENT_DRAFTS_SERVICE_URL}/drafts/{draft_id}", headers=auth_headers)
            return jsonify({"error": "failed to attach storage_path", "detail": _safe_detail(patch_resp)}), 502
        draft = patch_resp.json()

    return jsonify(draft), 201


@bp.route("/drafts/<draft_id>/caption", methods=["PATCH"])
def insert_caption(draft_id):
    """Set (or clear) a draft's caption.
    An empty string is a valid caption — most posts have no caption at all, and the frontend may finish typing one after the photo has already started uploading/scanning.
    ---
    tags:
      - Upload Post
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
          required:
            - text_content
          properties:
            text_content:
              type: string
              description: Use an empty string to clear the caption.
    responses:
      200:
        description: The updated draft.
        schema:
          $ref: "#/definitions/ContentDraft"
      400:
        description: text_content is missing or not a string.
      404:
        description: No draft with that id exists.
      502:
        description: The content_drafts service failed to update the draft.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or "text_content" not in data:
        return jsonify({"error": "text_content is required (use an empty string for no caption)"}), 400
    text_content = data["text_content"]
    if not isinstance(text_content, str):
        return jsonify({"error": "text_content must be a string"}), 400

    patch_resp = requests.patch(
        f"{CONTENT_DRAFTS_SERVICE_URL}/drafts/{draft_id}",
        json={"text_content": text_content},
        headers=forwarded_auth_headers(request),
    )
    if patch_resp.status_code == 404:
        return jsonify({"error": "draft not found"}), 404
    if patch_resp.status_code != 200:
        return jsonify({"error": "failed to insert caption", "detail": _safe_detail(patch_resp)}), 502
    return jsonify(patch_resp.json()), 200


@bp.route("/drafts/<draft_id>/original", methods=["GET"])
def get_original(draft_id):
    """Serve a draft's original file.
    Serves the original file's bytes over HTTP. This service is the only one that ever writes the file, to a GCS bucket rather than local disk — scan_draft and remediate_content run as separate Cloud Run services, each of which may be backed by multiple, independently-recycled container instances with their own local filesystem, so local disk can't be relied on to still have the file by the time a later request asks for it.
    ---
    tags:
      - Upload Post
    security:
      - BearerAuth: []
    produces:
      - image/*
    parameters:
      - in: path
        name: draft_id
        type: string
        required: true
    responses:
      200:
        description: The raw file bytes.
        schema:
          type: file
      400:
        description: The draft has no stored file.
      404:
        description: No draft with that id exists, or the stored file is missing from the bucket.
      502:
        description: The content_drafts service failed to return the draft.
    """
    draft_resp = requests.get(
        f"{CONTENT_DRAFTS_SERVICE_URL}/drafts/{draft_id}",
        headers=forwarded_auth_headers(request),
    )
    if draft_resp.status_code == 404:
        return jsonify({"error": "draft not found"}), 404
    if draft_resp.status_code != 200:
        return jsonify({"error": "failed to fetch draft"}), 502
    storage_path = draft_resp.json().get("storage_path")
    if not storage_path:
        return jsonify({"error": "draft has no stored file"}), 400

    data = trace_storage.download_bytes(storage_path)
    if data is None:
        return jsonify({"error": "file not found"}), 404
    return Response(data)


@bp.route("/drafts/<draft_id>/original", methods=["DELETE"])
def delete_original(draft_id):
    """Delete a draft's original file.
    Removes the stored original file for a draft that's being erased from history (manage_history's selective delete / retention sweep). Only this service ever writes that file, so only it can remove it — same reasoning as get_original above. Ownership is enforced by content_drafts' own GET, same as get_original; missing/already-gone is treated as success since the end state (no file) is what the caller wants either way.
    ---
    tags:
      - Upload Post
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: draft_id
        type: string
        required: true
    responses:
      204:
        description: File deleted (or there was none to delete).
      404:
        description: No draft with that id exists.
      502:
        description: The content_drafts service failed to return the draft.
    """
    draft_resp = requests.get(
        f"{CONTENT_DRAFTS_SERVICE_URL}/drafts/{draft_id}",
        headers=forwarded_auth_headers(request),
    )
    if draft_resp.status_code == 404:
        return jsonify({"error": "draft not found"}), 404
    if draft_resp.status_code != 200:
        return jsonify({"error": "failed to fetch draft"}), 502

    storage_path = draft_resp.json().get("storage_path")
    if storage_path:
        trace_storage.delete_blob(storage_path)

    return "", 204


# In professional setups, a Load Balancer and/or caller pings this /health URL every few seconds.
# If your code gets stuck in an infinite loop during a request,
# it will stop responding to /health.
@bp.get("/health")
def health():
    """Liveness check.
    Unauthenticated — polled frequently by the container orchestrator, so it must respond even while dependencies are unreachable.
    ---
    tags:
      - Health
    responses:
      200:
        description: The service process is alive.
    """
    return jsonify({"status": "ok"}), 200
