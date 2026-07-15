import pytest
from unittest.mock import MagicMock, patch
from flask import Flask

# Import the blueprint and the Edit model
# (Adjust the import path if your PYTHONPATH is configured differently)
from backend.atomic.edits.app.routes import edits_bp, Edit

@pytest.fixture
def app():
    """Creates a mock Flask application context specifically for the edits service."""
    app = Flask(__name__)
    app.register_blueprint(edits_bp)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Provides a test client to execute HTTP methods."""
    return app.test_client()


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


def test_create_edit_success(client, mock_db):
    """Tests successful creation of an edit item (POST /edits)."""
    with patch("backend.atomic.edits.app.routes.Edit") as MockEdit:
        # Stub the model instance and its to_dict response (Mockito when/thenReturn)
        mock_instance = MagicMock()
        mock_instance.to_dict.return_value = {
            "draft_id": "draft_123",
            "edit_type": "blur",
            "region_affected": "face_01"
        }
        MockEdit.return_value = mock_instance

        payload = {
            "draft_id": "draft_123",
            "edit_type": "blur",
            "region_affected": "face_01"
        }
        
        response = client.post("/edits", json=payload)

        # Assertions
        assert response.status_code == 201
        assert response.json["edit_type"] == "blur"
        
        # Verify db.session methods were invoked (Mockito verify)
        mock_db.session.add.assert_called_once_with(mock_instance)
        mock_db.session.commit.assert_called_once()


def test_list_edits_by_draft(client, mock_db):
    """Tests fetching edits filtered by draft_id using modern session syntax."""
    # Create mock instances
    mock_edit_1 = MagicMock()
    mock_edit_1.to_dict.return_value = {"edit_id": 1, "draft_id": "draft_1"}
    mock_edit_2 = MagicMock()
    mock_edit_2.to_dict.return_value = {"edit_id": 2, "draft_id": "draft_1"}

    # Mock the chain: db.session.scalars(db.select(...)).all()
    mock_db.session.scalars.return_value.all.return_value = [mock_edit_1, mock_edit_2]

    response = client.get("/drafts/draft_1/edits")

    assert response.status_code == 200
    assert len(response.json) == 2
    # Verify that the session was used to execute a select statement
    mock_db.session.scalars.assert_called_once()


def test_get_edit_success(client, mock_db):
    """Tests getting a single edit record by ID when it exists."""
    mock_edit = MagicMock()
    mock_edit.to_dict.return_value = {"edit_id": "edit_abc", "status": "pending"}
    mock_db.session.get.return_value = mock_edit

    response = client.get("/edits/edit_abc")

    assert response.status_code == 200
    assert response.json["edit_id"] == "edit_abc"
    mock_db.session.get.assert_called_once_with(Edit, "edit_abc")


def test_get_edit_not_found(client, mock_db):
    """Tests getting a non-existent edit record returns 404."""
    mock_db.session.get.return_value = None

    response = client.get("/edits/missing_id")

    assert response.status_code == 404
    assert response.json == {"error": "edit not found"}


def test_update_edit_status_success(client, mock_db):
    """Tests updating an edit item's status to a valid state (PATCH /edits/<id>)."""
    mock_edit = MagicMock()
    mock_edit.status = "pending"
    mock_edit.to_dict.return_value = {"edit_id": "edit_abc", "status": "applied"}
    mock_db.session.get.return_value = mock_edit

    response = client.patch("/edits/edit_abc", json={"status": "applied"})

    assert response.status_code == 200
    assert mock_edit.status == "applied"
    mock_db.session.commit.assert_called_once()


def test_update_edit_status_invalid(client, mock_db):
    """Tests that passing an illegal status option returns 400 Bad Request."""
    mock_edit = MagicMock()
    mock_db.session.get.return_value = mock_edit

    # "destroy" is not in ("pending", "applied", "reverted")
    response = client.patch("/edits/edit_abc", json={"status": "destroyed"})

    assert response.status_code == 400
    assert response.json == {"error": "invalid status"}
    # Commit must not be called on failed validation
    mock_db.session.commit.assert_not_called()


def test_update_edit_region_success(client, mock_db):
    """Tests updating just an edit's region_affected (PATCH /edits/<id>)."""
    mock_edit = MagicMock()
    mock_edit.region_affected = {"x": 0, "y": 0, "w": 10, "h": 10}
    mock_edit.to_dict.return_value = {"edit_id": "edit_abc", "region_affected": {"x": 5, "y": 6, "w": 20, "h": 30}}
    mock_db.session.get.return_value = mock_edit

    response = client.patch("/edits/edit_abc", json={"region_affected": {"x": 5, "y": 6, "w": 20, "h": 30}})

    assert response.status_code == 200
    assert mock_edit.region_affected == {"x": 5, "y": 6, "w": 20, "h": 30}
    mock_db.session.commit.assert_called_once()


def test_update_edit_status_and_region_together(client, mock_db):
    """Tests updating both status and region_affected in one PATCH."""
    mock_edit = MagicMock()
    mock_edit.to_dict.return_value = {"edit_id": "edit_abc", "status": "applied"}
    mock_db.session.get.return_value = mock_edit

    response = client.patch(
        "/edits/edit_abc",
        json={"status": "applied", "region_affected": {"x": 1, "y": 2, "w": 3, "h": 4}},
    )

    assert response.status_code == 200
    assert mock_edit.status == "applied"
    assert mock_edit.region_affected == {"x": 1, "y": 2, "w": 3, "h": 4}
    mock_db.session.commit.assert_called_once()


def test_update_edit_region_invalid_shape(client, mock_db):
    """Tests that a region_affected missing a required key returns 400."""
    mock_edit = MagicMock()
    mock_db.session.get.return_value = mock_edit

    response = client.patch("/edits/edit_abc", json={"region_affected": {"x": 1, "y": 2, "w": 3}})

    assert response.status_code == 400
    assert response.json == {"error": "invalid region_affected"}
    mock_db.session.commit.assert_not_called()


def test_update_edit_no_fields(client, mock_db):
    """Tests that a PATCH with neither status nor region_affected returns 400."""
    mock_edit = MagicMock()
    mock_db.session.get.return_value = mock_edit

    response = client.patch("/edits/edit_abc", json={})

    assert response.status_code == 400
    assert response.json == {"error": "must provide status and/or region_affected"}
    mock_db.session.commit.assert_not_called()


def test_delete_edit_success(client, mock_db):
    """Tests deleting an edit item successfully (DELETE /edits/<id>)."""
    mock_edit = MagicMock()
    mock_db.session.get.return_value = mock_edit

    response = client.delete("/edits/edit_abc")

    assert response.status_code == 204
    assert response.data == b""  # 204 responses have empty bodies
    mock_db.session.delete.assert_called_once_with(mock_edit)
    mock_db.session.commit.assert_called_once()