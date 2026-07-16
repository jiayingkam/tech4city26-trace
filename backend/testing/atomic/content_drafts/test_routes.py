import pytest
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import create_access_token

from backend.atomic.content_drafts.app.routes import bp, ContentDrafts
from backend.shared.trace_auth import init_auth


@pytest.fixture
def app():
    app = Flask(__name__)
    # content_drafts' real auth gate lives in app.py's before_request (via
    # init_auth), not a per-route decorator, so the test app needs the same
    # hook registered for get_jwt_identity() to have anything to read.
    with patch.dict("os.environ", {"JWT_SECRET_KEY": "test-secret"}):
        init_auth(app)
    app.register_blueprint(bp)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def mock_db():
    with patch("backend.atomic.content_drafts.app.routes.db") as mocked_db:
        yield mocked_db


def auth_header(app, user_id="user_abc"):
    with app.app_context():
        token = create_access_token(identity=user_id)
    return {"Authorization": f"Bearer {token}"}


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200


def test_create_draft_requires_matching_owner(app, client, mock_db):
    response = client.post(
        "/drafts",
        json={"owner_id": "someone_else", "content_type": "image"},
        headers=auth_header(app, user_id="user_abc"),
    )

    assert response.status_code == 403
    mock_db.session.add.assert_not_called()


def test_create_draft_success(app, client, mock_db):
    with patch("backend.atomic.content_drafts.app.routes.ContentDrafts") as MockDraft:
        mock_instance = MagicMock()
        mock_instance.to_dict.return_value = {"draft_id": "draft_1", "owner_id": "user_abc"}
        MockDraft.return_value = mock_instance

        response = client.post(
            "/drafts",
            json={"owner_id": "user_abc", "content_type": "image"},
            headers=auth_header(app, user_id="user_abc"),
        )

        assert response.status_code == 201
        mock_db.session.add.assert_called_once_with(mock_instance)


def test_get_draft_forbidden_for_other_owner(app, client, mock_db):
    mock_draft = MagicMock()
    mock_draft.owner_id = "someone_else"
    mock_db.session.get.return_value = mock_draft

    response = client.get("/drafts/draft_1", headers=auth_header(app, user_id="user_abc"))

    assert response.status_code == 403


def test_get_draft_success(app, client, mock_db):
    mock_draft = MagicMock()
    mock_draft.owner_id = "user_abc"
    mock_draft.to_dict.return_value = {"draft_id": "draft_1", "owner_id": "user_abc"}
    mock_db.session.get.return_value = mock_draft

    response = client.get("/drafts/draft_1", headers=auth_header(app, user_id="user_abc"))

    assert response.status_code == 200


def test_list_drafts_for_owner_forbidden_for_other_user(app, client, mock_db):
    response = client.get("/users/someone_else/drafts", headers=auth_header(app, user_id="user_abc"))

    assert response.status_code == 403
    mock_db.session.scalars.assert_not_called()


def test_delete_draft_forbidden_for_other_owner(app, client, mock_db):
    mock_draft = MagicMock()
    mock_draft.owner_id = "someone_else"
    mock_db.session.get.return_value = mock_draft

    response = client.delete("/drafts/draft_1", headers=auth_header(app, user_id="user_abc"))

    assert response.status_code == 403
    mock_db.session.delete.assert_not_called()
