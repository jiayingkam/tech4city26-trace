import pytest
from unittest.mock import MagicMock, patch
from flask import Flask
from datetime import datetime, timezone, timedelta
from backend.atomic.quarantine_items.app.routes import quarantine_bp, QuarantineItem

@pytest.fixture
def app():
    """Creates a mock Flask application context."""
    app = Flask(__name__)
    app.register_blueprint(quarantine_bp)
    app.register_blueprint(bp)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Provides a test client to make HTTP calls (GET, POST, etc.)."""
    return app.test_client()


@pytest.fixture
def mock_db():
    """
    Mocks the db object entirely. 
    Using 'yield' allows us to clean up after the test finishes (@AfterEach).
    """
    with patch("routes.db") as mocked_db:
        yield mocked_db


# ==========================================
# TEST CASES
# ==========================================

def test_health_endpoint(client):
    """Simple test for the health check route."""
    response = client.get("/health")
    
    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_get_quarantine_item_success(client, mock_db):
    """Tests GET /quarantine/<id> when the item exists."""
    # 1. Arrange (Stubbing like Mockito's 'when')
    mock_item = MagicMock()
    mock_item.to_dict.return_value = {"quarantine_id": "123", "reason": "Spam"}
    mock_db.session.get.return_value = mock_item

    # 2. Act
    response = client.get("/quarantine/123")

    # 3. Assert (JUnit assertions)
    assert response.status_code == 200
    assert response.json["quarantine_id"] == "123"
    
    # Verification (Mockito verify equivalent)
    mock_db.session.get.assert_called_once_with(QuarantineItem, "123")


def test_get_quarantine_item_not_found(client, mock_db):
    """Tests GET /quarantine/<id> when the item does not exist."""
    # Stub db.session.get to return None
    mock_db.session.get.return_value = None

    response = client.get("/quarantine/999")

    assert response.status_code == 404
    assert response.json == {"error": "quarantine item not found"}


def test_create_quarantine(client, mock_db):
    """Tests POST /quarantine."""
    # We mock the QuarantineItem constructor and its to_dict method
    with patch("routes.QuarantineItem") as MockItem:
        mock_instance = MagicMock()
        mock_instance.to_dict.return_value = {"draft_id": "abc", "reason": "suspicious"}
        MockItem.return_value = mock_instance

        payload = {"draft_id": "abc", "reason": "suspicious", "cooldown_minutes": 10}
        
        response = client.post("/quarantine", json=payload)

        assert response.status_code == 201
        assert response.json["draft_id"] == "abc"
        
        # Verify db tracking actions occurred
        mock_db.session.add.assert_called_once_with(mock_instance)
        mock_db.session.commit.assert_called_once()


def test_cooldown_status(client, mock_db):
    """Tests GET /quarantine/<id>/cooldown calculating remaining time."""
    mock_item = MagicMock()
    mock_item.quarantine_id = "xyz"
    # Set expiration to 10 minutes in the future
    mock_item.cooldown_expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
    mock_db.session.get.return_value = mock_item

    response = client.get("/quarantine/xyz/cooldown")

    assert response.status_code == 200
    assert response.json["expired"] is False
    assert response.json["seconds_remaining"] > 590  # roughly 600 seconds