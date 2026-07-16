import pytest
from unittest.mock import MagicMock, patch
from flask import Flask
from datetime import datetime, timezone, timedelta
from flask_jwt_extended import create_access_token

from backend.atomic.quarantine_items.app.routes import quarantine_bp, QuarantineItem
from backend.shared.trace_auth import init_auth

USER_ID = "user_abc"


@pytest.fixture
def app():
    """Creates a mock Flask application context."""
    app = Flask(__name__)
    with patch.dict("os.environ", {"JWT_SECRET_KEY": "test-secret"}):
        init_auth(app)
    app.register_blueprint(quarantine_bp)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Provides a test client to make HTTP calls (GET, POST, etc.)."""
    return app.test_client()


@pytest.fixture
def auth_headers(app):
    with app.app_context():
        token = create_access_token(identity=USER_ID)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def mock_db():
    """
    Mocks the db object entirely.
    Using 'yield' allows us to clean up after the test finishes (@AfterEach).
    """
    # The fully-qualified module path is required here — a bare "routes"
    # doesn't resolve to anything and silently breaks every test using this
    # fixture (they'd error out at collection time, not fail at assertion time).
    with patch("backend.atomic.quarantine_items.app.routes.db") as mocked_db:
        yield mocked_db


# ==========================================
# TEST CASES
# ==========================================

def test_health_endpoint(client):
    """Simple test for the health check route."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_get_quarantine_item_success(client, mock_db, auth_headers):
    """Tests GET /quarantine/<id> when the item exists."""
    # 1. Arrange (Stubbing like Mockito's 'when')
    mock_item = MagicMock()
    mock_item.owner_id = USER_ID
    mock_item.to_dict.return_value = {"quarantine_id": "123", "reason": "Spam"}
    mock_db.session.get.return_value = mock_item

    # 2. Act
    response = client.get("/quarantine/123", headers=auth_headers)

    # 3. Assert (JUnit assertions)
    assert response.status_code == 200
    assert response.json["quarantine_id"] == "123"

    # Verification (Mockito verify equivalent)
    mock_db.session.get.assert_called_once_with(QuarantineItem, "123")


def test_get_quarantine_item_not_found(client, mock_db, auth_headers):
    """Tests GET /quarantine/<id> when the item does not exist."""
    # Stub db.session.get to return None
    mock_db.session.get.return_value = None

    response = client.get("/quarantine/999", headers=auth_headers)

    assert response.status_code == 404
    assert response.json == {"error": "quarantine item not found"}


def test_get_quarantine_item_forbidden_for_other_owner(client, mock_db, auth_headers):
    mock_item = MagicMock()
    mock_item.owner_id = "someone_else"
    mock_db.session.get.return_value = mock_item

    response = client.get("/quarantine/123", headers=auth_headers)

    assert response.status_code == 403


def test_list_quarantine_by_draft(client, mock_db, auth_headers):
    """Tests fetching quarantine items filtered by draft_id."""
    # Create mock items
    mock_item = MagicMock()
    mock_item.to_dict.return_value = {"quarantine_id": "q1", "draft_id": "d1"}

    # Mock the chain: db.session.scalars(stmt).all()
    mock_db.session.scalars.return_value.all.return_value = [mock_item]

    response = client.get("/drafts/d1/quarantine", headers=auth_headers)

    assert response.status_code == 200
    assert len(response.json) == 1
    assert response.json[0]["quarantine_id"] == "q1"

    # Verify the session was used
    mock_db.session.scalars.assert_called_once()


def test_create_quarantine(client, mock_db, auth_headers):
    """Tests POST /quarantine."""
    # We mock the QuarantineItem constructor and its to_dict method
    with patch("backend.atomic.quarantine_items.app.routes.QuarantineItem") as MockItem:
        mock_instance = MagicMock()
        mock_instance.to_dict.return_value = {"draft_id": "abc", "owner_id": USER_ID, "reason": "suspicious"}
        MockItem.return_value = mock_instance

        payload = {"draft_id": "abc", "reason": "suspicious", "cooldown_minutes": 10}

        response = client.post("/quarantine", json=payload, headers=auth_headers)

        assert response.status_code == 201
        assert response.json["draft_id"] == "abc"
        assert MockItem.call_args.kwargs["owner_id"] == USER_ID

        # Verify db tracking actions occurred
        mock_db.session.add.assert_called_once_with(mock_instance)
        mock_db.session.commit.assert_called_once()


def test_cooldown_status(client, mock_db, auth_headers):
    """Tests GET /quarantine/<id>/cooldown calculating remaining time."""
    mock_item = MagicMock()
    mock_item.owner_id = USER_ID
    mock_item.quarantine_id = "xyz"
    # Set expiration to 10 minutes in the future
    mock_item.cooldown_expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
    mock_db.session.get.return_value = mock_item

    response = client.get("/quarantine/xyz/cooldown", headers=auth_headers)

    assert response.status_code == 200
    assert response.json["expired"] is False
    assert response.json["seconds_remaining"] > 590  # roughly 600 seconds


def test_delete_quarantine_for_draft_bulk(client, mock_db, auth_headers):
    """Tests the cascade-delete bulk route used by manage_history."""
    mock_item_1, mock_item_2 = MagicMock(), MagicMock()
    mock_db.session.scalars.return_value.all.return_value = [mock_item_1, mock_item_2]

    response = client.delete("/drafts/d1/quarantine", headers=auth_headers)

    assert response.status_code == 204
    assert mock_db.session.delete.call_count == 2
    mock_db.session.commit.assert_called_once()
