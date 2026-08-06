import pytest
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from backend.retention_guard.atomic.business_admins.app.routes import business_admins_bp, BusinessAdmin


@pytest.fixture
def app():
    """Creates a mock Flask application context specifically for business_admins."""
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "test-secret"
    JWTManager(app)
    app.register_blueprint(business_admins_bp)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def mock_db():
    with patch("backend.retention_guard.atomic.business_admins.app.routes.db") as mocked_db:
        yield mocked_db


def auth_header(app, admin_id="admin_abc"):
    with app.app_context():
        token = create_access_token(identity=admin_id)
    return {"Authorization": f"Bearer {token}"}


# ==========================================
# TEST CASES
# ==========================================

def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_signup_success(client, mock_db):
    mock_db.session.scalar.return_value = None  # no existing admin with that email

    with patch("backend.retention_guard.atomic.business_admins.app.routes.BusinessAdmin") as MockAdmin:
        mock_instance = MagicMock()
        mock_instance.admin_id = "admin_abc"
        mock_instance.to_dict.return_value = {"admin_id": "admin_abc", "email": "a@fakecorp.com", "business_name": "FakeCorp"}
        MockAdmin.return_value = mock_instance

        response = client.post(
            "/signup", json={"email": "a@fakecorp.com", "password": "hunter2", "business_name": "FakeCorp"}
        )

        assert response.status_code == 201
        assert "token" in response.json
        assert response.json["admin"]["business_name"] == "FakeCorp"
        mock_db.session.add.assert_called_once_with(mock_instance)
        mock_db.session.commit.assert_called_once()


def test_signup_duplicate_email(client, mock_db):
    mock_db.session.scalar.return_value = MagicMock()  # an existing admin already has this email

    response = client.post(
        "/signup", json={"email": "a@fakecorp.com", "password": "hunter2", "business_name": "FakeCorp"}
    )

    assert response.status_code == 409
    mock_db.session.add.assert_not_called()


def test_signup_missing_fields(client, mock_db):
    response = client.post("/signup", json={"email": "a@fakecorp.com"})

    assert response.status_code == 400


def test_login_success(client, mock_db):
    mock_admin = MagicMock()
    mock_admin.password_hash = "pbkdf2:sha256:hashed"
    mock_admin.admin_id = "admin_abc"
    mock_admin.to_dict.return_value = {"admin_id": "admin_abc", "email": "a@fakecorp.com"}
    mock_db.session.scalar.return_value = mock_admin

    with patch("backend.retention_guard.atomic.business_admins.app.routes.check_password_hash", return_value=True):
        response = client.post("/login", json={"email": "a@fakecorp.com", "password": "hunter2"})

    assert response.status_code == 200
    assert "token" in response.json


def test_login_invalid_password(client, mock_db):
    mock_admin = MagicMock()
    mock_admin.password_hash = "pbkdf2:sha256:hashed"
    mock_db.session.scalar.return_value = mock_admin

    with patch("backend.retention_guard.atomic.business_admins.app.routes.check_password_hash", return_value=False):
        response = client.post("/login", json={"email": "a@fakecorp.com", "password": "wrong"})

    assert response.status_code == 401


def test_login_unknown_email(client, mock_db):
    mock_db.session.scalar.return_value = None

    response = client.post("/login", json={"email": "nobody@fakecorp.com", "password": "hunter2"})

    assert response.status_code == 401


def test_me_requires_auth(client):
    response = client.get("/me")
    assert response.status_code == 401


def test_me_success(app, client, mock_db):
    mock_admin = MagicMock()
    mock_admin.to_dict.return_value = {"admin_id": "admin_abc", "email": "a@fakecorp.com"}
    mock_db.session.get.return_value = mock_admin

    response = client.get("/me", headers=auth_header(app))

    assert response.status_code == 200
    mock_db.session.get.assert_called_once_with(BusinessAdmin, "admin_abc")


def test_me_not_found(app, client, mock_db):
    mock_db.session.get.return_value = None

    response = client.get("/me", headers=auth_header(app))

    assert response.status_code == 404


def test_impersonate_internal_success(client, mock_db):
    mock_db.session.get.return_value = MagicMock()  # admin exists

    response = client.post("/internal/impersonate", json={"admin_id": "admin_abc"})

    assert response.status_code == 200
    assert "token" in response.json


def test_impersonate_internal_unknown_admin(client, mock_db):
    mock_db.session.get.return_value = None

    response = client.post("/internal/impersonate", json={"admin_id": "ghost"})

    assert response.status_code == 404
