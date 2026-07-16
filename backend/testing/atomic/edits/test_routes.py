import pytest
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import create_access_token

from backend.atomic.edits.app.routes import edits_bp, Edit
from backend.shared.trace_auth import init_auth

USER_ID = "user_abc"


@pytest.fixture
def app():
    """Creates a mock Flask application context specifically for the edits service."""
    app = Flask(__name__)
    with patch.dict("os.environ", {"JWT_SECRET_KEY": "test-secret"}):
        init_auth(app)
    app.register_blueprint(edits_bp)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Provides a test client to execute HTTP methods."""
    return app.test_client()


@pytest.fixture
def auth_headers(app):
    with app.app_context():
        token = create_access_token(identity=USER_ID)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def mock_db():
    """Mocks the database object to prevent real database interactions."""
    with patch("backend.atomic.edits.app.routes.db") as mocked_db:
        yield mocked_db


# ==========================================
# TEST CASES
# ==========================================

def test_health_endpoint(client):
    """Verifies the health check endpoint returns 200 OK."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_create_edit_requires_auth(client):
    """Every route except /health is behind the auth gate — no token, no dice."""
    response = client.post("/edits", json={"draft_id": "draft_123", "edit_type": "blur"})
    assert response.status_code == 401


def test_create_edit_success(client, mock_db, auth_headers):
    """Tests successful creation of an edit item (POST /edits)."""
    with patch("backend.atomic.edits.app.routes.Edit") as MockEdit:
        # Stub the model instance and its to_dict response (Mockito when/thenReturn)
        mock_instance = MagicMock()
        mock_instance.to_dict.return_value = {
            "draft_id": "draft_123",
            "owner_id": USER_ID,
            "edit_type": "blur",
            "region_affected": "face_01"
        }
        MockEdit.return_value = mock_instance

        payload = {
            "draft_id": "draft_123",
            "edit_type": "blur",
            "region_affected": "face_01"
        }

        response = client.post("/edits", json=payload, headers=auth_headers)

        # Assertions
        assert response.status_code == 201
        assert response.json["edit_type"] == "blur"
        MockEdit.assert_called_once_with(
            draft_id="draft_123",
            owner_id=USER_ID,
            detection_id=None,
            edit_type="blur",
            region_affected="face_01",
        )

        # Verify db.session methods were invoked (Mockito verify)
        mock_db.session.add.assert_called_once_with(mock_instance)
        mock_db.session.commit.assert_called_once()


def test_list_edits_by_draft(client, mock_db, auth_headers):
    """Tests fetching edits filtered by draft_id using modern session syntax."""
    # Create mock instances
    mock_edit_1 = MagicMock()
    mock_edit_1.to_dict.return_value = {"edit_id": 1, "draft_id": "draft_1"}
    mock_edit_2 = MagicMock()
    mock_edit_2.to_dict.return_value = {"edit_id": 2, "draft_id": "draft_1"}

    # Mock the chain: db.session.scalars(db.select(...)).all()
    mock_db.session.scalars.return_value.all.return_value = [mock_edit_1, mock_edit_2]

    response = client.get("/drafts/draft_1/edits", headers=auth_headers)

    assert response.status_code == 200
    assert len(response.json) == 2
    # Verify that the session was used to execute a select statement
    mock_db.session.scalars.assert_called_once()


def test_get_edit_success(client, mock_db, auth_headers):
    """Tests getting a single edit record by ID when it exists."""
    mock_edit = MagicMock()
    mock_edit.owner_id = USER_ID
    mock_edit.to_dict.return_value = {"edit_id": "edit_abc", "status": "pending"}
    mock_db.session.get.return_value = mock_edit

    response = client.get("/edits/edit_abc", headers=auth_headers)

    assert response.status_code == 200
    assert response.json["edit_id"] == "edit_abc"
    mock_db.session.get.assert_called_once_with(Edit, "edit_abc")


def test_get_edit_not_found(client, mock_db, auth_headers):
    """Tests getting a non-existent edit record returns 404."""
    mock_db.session.get.return_value = None

    response = client.get("/edits/missing_id", headers=auth_headers)

    assert response.status_code == 404
    assert response.json == {"error": "edit not found"}


def test_get_edit_forbidden_for_other_owner(client, mock_db, auth_headers):
    """A real edit that belongs to someone else reads as forbidden, not found-then-shown."""
    mock_edit = MagicMock()
    mock_edit.owner_id = "someone_else"
    mock_db.session.get.return_value = mock_edit

    response = client.get("/edits/edit_abc", headers=auth_headers)

    assert response.status_code == 403


def test_update_edit_status_success(client, mock_db, auth_headers):
    """Tests updating an edit item's status to a valid state (PATCH /edits/<id>)."""
    mock_edit = MagicMock()
    mock_edit.owner_id = USER_ID
    mock_edit.status = "pending"
    mock_edit.to_dict.return_value = {"edit_id": "edit_abc", "status": "applied"}
    mock_db.session.get.return_value = mock_edit

    response = client.patch("/edits/edit_abc", json={"status": "applied"}, headers=auth_headers)

    assert response.status_code == 200
    assert mock_edit.status == "applied"
    mock_db.session.commit.assert_called_once()


def test_update_edit_status_invalid(client, mock_db, auth_headers):
    """Tests that passing an illegal status option returns 400 Bad Request."""
    mock_edit = MagicMock()
    mock_edit.owner_id = USER_ID
    mock_db.session.get.return_value = mock_edit

    # "destroy" is not in ("pending", "applied", "reverted")
    response = client.patch("/edits/edit_abc", json={"status": "destroyed"}, headers=auth_headers)

    assert response.status_code == 400
    assert response.json == {"error": "invalid status"}
    # Commit must not be called on failed validation
    mock_db.session.commit.assert_not_called()


def test_update_edit_region_success(client, mock_db, auth_headers):
    """Tests updating just an edit's region_affected (PATCH /edits/<id>)."""
    mock_edit = MagicMock()
    mock_edit.owner_id = USER_ID
    mock_edit.region_affected = {"x": 0, "y": 0, "w": 10, "h": 10}
    mock_edit.to_dict.return_value = {"edit_id": "edit_abc", "region_affected": {"x": 5, "y": 6, "w": 20, "h": 30}}
    mock_db.session.get.return_value = mock_edit

    response = client.patch(
        "/edits/edit_abc", json={"region_affected": {"x": 5, "y": 6, "w": 20, "h": 30}}, headers=auth_headers
    )

    assert response.status_code == 200
    assert mock_edit.region_affected == {"x": 5, "y": 6, "w": 20, "h": 30}
    mock_db.session.commit.assert_called_once()


def test_update_edit_status_and_region_together(client, mock_db, auth_headers):
    """Tests updating both status and region_affected in one PATCH."""
    mock_edit = MagicMock()
    mock_edit.owner_id = USER_ID
    mock_edit.to_dict.return_value = {"edit_id": "edit_abc", "status": "applied"}
    mock_db.session.get.return_value = mock_edit

    response = client.patch(
        "/edits/edit_abc",
        json={"status": "applied", "region_affected": {"x": 1, "y": 2, "w": 3, "h": 4}},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert mock_edit.status == "applied"
    assert mock_edit.region_affected == {"x": 1, "y": 2, "w": 3, "h": 4}
    mock_db.session.commit.assert_called_once()


def test_update_edit_region_invalid_shape(client, mock_db, auth_headers):
    """Tests that a region_affected missing a required key returns 400."""
    mock_edit = MagicMock()
    mock_edit.owner_id = USER_ID
    mock_db.session.get.return_value = mock_edit

    response = client.patch(
        "/edits/edit_abc", json={"region_affected": {"x": 1, "y": 2, "w": 3}}, headers=auth_headers
    )

    assert response.status_code == 400
    assert response.json == {"error": "invalid region_affected"}
    mock_db.session.commit.assert_not_called()


def test_update_edit_no_fields(client, mock_db, auth_headers):
    """Tests that a PATCH with neither status nor region_affected returns 400."""
    mock_edit = MagicMock()
    mock_edit.owner_id = USER_ID
    mock_db.session.get.return_value = mock_edit

    response = client.patch("/edits/edit_abc", json={}, headers=auth_headers)

    assert response.status_code == 400
    assert response.json == {"error": "must provide status and/or region_affected"}
    mock_db.session.commit.assert_not_called()


def test_delete_edit_success(client, mock_db, auth_headers):
    """Tests deleting an edit item successfully (DELETE /edits/<id>)."""
    mock_edit = MagicMock()
    mock_edit.owner_id = USER_ID
    mock_db.session.get.return_value = mock_edit

    response = client.delete("/edits/edit_abc", headers=auth_headers)

    assert response.status_code == 204
    assert response.data == b""  # 204 responses have empty bodies
    mock_db.session.delete.assert_called_once_with(mock_edit)
    mock_db.session.commit.assert_called_once()


def test_delete_edits_for_draft_bulk(client, mock_db, auth_headers):
    """Tests the cascade-delete bulk route used by manage_history."""
    mock_edit_1 = MagicMock()
    mock_edit_2 = MagicMock()
    mock_db.session.scalars.return_value.all.return_value = [mock_edit_1, mock_edit_2]

    response = client.delete("/drafts/draft_1/edits", headers=auth_headers)

    assert response.status_code == 204
    assert mock_db.session.delete.call_count == 2
    mock_db.session.commit.assert_called_once()
