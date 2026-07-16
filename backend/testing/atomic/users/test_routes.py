import pytest
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from backend.atomic.users.app.routes import users_bp, User


@pytest.fixture
def app():
    """Creates a mock Flask application context specifically for the users service."""
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "test-secret"
    JWTManager(app)
    app.register_blueprint(users_bp)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Provides a test client to execute HTTP methods."""
    return app.test_client()


@pytest.fixture
def mock_db():
    """Mocks the database object to prevent real database interactions."""
    with patch("backend.atomic.users.app.routes.db") as mocked_db:
        yield mocked_db


def auth_header(app, user_id="user_abc"):
    with app.app_context():
        token = create_access_token(identity=user_id)
    return {"Authorization": f"Bearer {token}"}


# ==========================================
# TEST CASES
# ==========================================

def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_signup_success(client, mock_db):
    mock_db.session.scalar.return_value = None  # no existing user with that email

    with patch("backend.atomic.users.app.routes.User") as MockUser:
        mock_instance = MagicMock()
        mock_instance.user_id = "user_abc"
        mock_instance.to_dict.return_value = {"user_id": "user_abc", "email": "mia@example.com"}
        MockUser.return_value = mock_instance

        response = client.post("/signup", json={"email": "mia@example.com", "password": "hunter2"})

        assert response.status_code == 201
        assert "token" in response.json
        assert response.json["user"]["email"] == "mia@example.com"
        mock_db.session.add.assert_called_once_with(mock_instance)
        mock_db.session.commit.assert_called_once()


def test_signup_duplicate_email(client, mock_db):
    mock_db.session.scalar.return_value = MagicMock()  # an existing user already has this email

    response = client.post("/signup", json={"email": "mia@example.com", "password": "hunter2"})

    assert response.status_code == 409
    mock_db.session.add.assert_not_called()


def test_signup_missing_fields(client, mock_db):
    response = client.post("/signup", json={"email": "mia@example.com"})

    assert response.status_code == 400
    assert response.json == {"error": "email and password are required"}


def test_login_success(client, mock_db):
    mock_user = MagicMock()
    mock_user.password_hash = "pbkdf2:sha256:hashed"
    mock_user.user_id = "user_abc"
    mock_user.to_dict.return_value = {"user_id": "user_abc", "email": "mia@example.com"}
    mock_db.session.scalar.return_value = mock_user

    with patch("backend.atomic.users.app.routes.check_password_hash", return_value=True):
        response = client.post("/login", json={"email": "mia@example.com", "password": "hunter2"})

    assert response.status_code == 200
    assert "token" in response.json


def test_login_invalid_password(client, mock_db):
    mock_user = MagicMock()
    mock_user.password_hash = "pbkdf2:sha256:hashed"
    mock_db.session.scalar.return_value = mock_user

    with patch("backend.atomic.users.app.routes.check_password_hash", return_value=False):
        response = client.post("/login", json={"email": "mia@example.com", "password": "wrong"})

    assert response.status_code == 401


def test_login_unknown_email(client, mock_db):
    mock_db.session.scalar.return_value = None

    response = client.post("/login", json={"email": "nobody@example.com", "password": "hunter2"})

    assert response.status_code == 401


def test_me_requires_auth(client):
    response = client.get("/me")
    assert response.status_code == 401


def test_me_success(app, client, mock_db):
    mock_user = MagicMock()
    mock_user.to_dict.return_value = {"user_id": "user_abc", "email": "mia@example.com"}
    mock_db.session.get.return_value = mock_user

    response = client.get("/me", headers=auth_header(app))

    assert response.status_code == 200
    mock_db.session.get.assert_called_once_with(User, "user_abc")


def test_update_settings_forbidden_for_other_user(app, client, mock_db):
    response = client.patch(
        "/users/someone_else/settings",
        json={"retention_mode": "manual"},
        headers=auth_header(app, user_id="user_abc"),
    )

    assert response.status_code == 403
    mock_db.session.commit.assert_not_called()


def test_update_settings_success(app, client, mock_db):
    mock_user = MagicMock()
    mock_user.to_dict.return_value = {"user_id": "user_abc", "retention_mode": "manual"}
    mock_db.session.get.return_value = mock_user

    response = client.patch(
        "/users/user_abc/settings",
        json={"retention_mode": "manual"},
        headers=auth_header(app, user_id="user_abc"),
    )

    assert response.status_code == 200
    assert mock_user.retention_mode == "manual"
    mock_db.session.commit.assert_called_once()


def test_update_settings_invalid_mode(app, client, mock_db):
    mock_user = MagicMock()
    mock_db.session.get.return_value = mock_user

    response = client.patch(
        "/users/user_abc/settings",
        json={"retention_mode": "sometimes"},
        headers=auth_header(app, user_id="user_abc"),
    )

    assert response.status_code == 400
    mock_db.session.commit.assert_not_called()


def test_impersonate_internal_success(client, mock_db):
    mock_db.session.get.return_value = MagicMock()  # user exists

    response = client.post("/internal/impersonate", json={"user_id": "user_abc"})

    assert response.status_code == 200
    assert "token" in response.json


def test_impersonate_internal_unknown_user(client, mock_db):
    mock_db.session.get.return_value = None

    response = client.post("/internal/impersonate", json={"user_id": "ghost"})

    assert response.status_code == 404


def test_list_users_internal_filters_by_retention_mode(client, mock_db):
    mock_user = MagicMock()
    mock_user.to_dict.return_value = {"user_id": "user_abc", "retention_mode": "auto_expire"}
    mock_db.session.scalars.return_value.all.return_value = [mock_user]

    # No auth header at all — this route isn't behind the user-JWT hook in
    # the real app (it's gated by INTERNAL_API_KEY in app.py's before_request
    # instead), so the blueprint-only test app should let it through.
    response = client.get("/internal/users?retention_mode=auto_expire")

    assert response.status_code == 200
    assert len(response.json) == 1
