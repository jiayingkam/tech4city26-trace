import pytest
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from backend.retention_guard.atomic.data_sources.app.routes import data_sources_bp, DataSource, ClassifiedColumn

OWNER_ID = "admin_abc"


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "test-secret"
    JWTManager(app)
    app.register_blueprint(data_sources_bp)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def mock_db():
    with patch("backend.retention_guard.atomic.data_sources.app.routes.db") as mocked_db:
        yield mocked_db


@pytest.fixture(autouse=True)
def encryption_key():
    from cryptography.fernet import Fernet
    with patch.dict("os.environ", {"CONN_STRING_ENCRYPTION_KEY": Fernet.generate_key().decode()}):
        # Reset trace_crypto's lazily-cached Fernet instance between tests —
        # otherwise the first test to run wins and later tests' env var
        # patches are silently ignored.
        import trace_crypto
        trace_crypto._fernet = None
        yield
        trace_crypto._fernet = None


def auth_header(app, owner_id=OWNER_ID):
    with app.app_context():
        token = create_access_token(identity=owner_id)
    return {"Authorization": f"Bearer {token}"}


# ==========================================
# TEST CASES
# ==========================================

def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_create_data_source_encrypts_and_never_echoes_plaintext(app, client, mock_db):
    response = client.post(
        "/data-sources",
        json={"name": "FakeCorp Customer DB", "connection_string": "postgresql://demo:demo@fakecorp:5432/fakecorp"},
        headers=auth_header(app),
    )

    assert response.status_code == 201
    assert "connection_string" not in response.json
    assert "connection_string_encrypted" not in response.json
    mock_db.session.add.assert_called_once()
    added = mock_db.session.add.call_args[0][0]
    assert isinstance(added, DataSource)
    assert added.connection_string_encrypted != "postgresql://demo:demo@fakecorp:5432/fakecorp"
    mock_db.session.commit.assert_called_once()


def test_create_data_source_rejects_unsupported_db_type(app, client, mock_db):
    response = client.post(
        "/data-sources",
        json={"name": "x", "connection_string": "mysql://...", "db_type": "mysql"},
        headers=auth_header(app),
    )
    assert response.status_code == 400


def test_create_data_source_missing_fields(app, client, mock_db):
    response = client.post("/data-sources", json={"name": "x"}, headers=auth_header(app))
    assert response.status_code == 400


def test_get_data_source_not_owned_is_404(app, client, mock_db):
    other_owners_source = MagicMock()
    other_owners_source.owner_id = "someone_else"
    mock_db.session.get.return_value = other_owners_source

    response = client.get("/data-sources/ds1", headers=auth_header(app))

    assert response.status_code == 404


def test_get_data_source_success(app, client, mock_db):
    source = MagicMock()
    source.owner_id = OWNER_ID
    source.to_dict.return_value = {"data_source_id": "ds1", "owner_id": OWNER_ID}
    mock_db.session.get.return_value = source

    response = client.get("/data-sources/ds1", headers=auth_header(app))

    assert response.status_code == 200
    assert response.json["data_source_id"] == "ds1"


def test_delete_data_source_cascades_classified_columns(app, client, mock_db):
    source = MagicMock()
    source.owner_id = OWNER_ID
    source.data_source_id = "ds1"
    mock_db.session.get.return_value = source

    response = client.delete("/data-sources/ds1", headers=auth_header(app))

    assert response.status_code == 204
    mock_db.session.execute.assert_called_once()  # the classified_columns bulk delete
    mock_db.session.delete.assert_called_once_with(source)


def test_create_classified_column_success(app, client, mock_db):
    source = MagicMock()
    source.owner_id = OWNER_ID
    source.data_source_id = "ds1"
    mock_db.session.get.return_value = source

    response = client.post(
        "/data-sources/ds1/classified-columns",
        json={"table_name": "customers", "column_name": "email", "column_role": "pii"},
        headers=auth_header(app),
    )

    assert response.status_code == 201
    mock_db.session.add.assert_called_once()
    added = mock_db.session.add.call_args[0][0]
    assert isinstance(added, ClassifiedColumn)
    assert added.column_role == "pii"


def test_create_classified_column_invalid_role(app, client, mock_db):
    source = MagicMock()
    source.owner_id = OWNER_ID
    mock_db.session.get.return_value = source

    response = client.post(
        "/data-sources/ds1/classified-columns",
        json={"table_name": "customers", "column_name": "email", "column_role": "not_a_real_role"},
        headers=auth_header(app),
    )

    assert response.status_code == 400


def test_get_connection_internal_returns_decrypted_string(app, client, mock_db):
    from trace_crypto import encrypt

    source = MagicMock()
    source.connection_string_encrypted = encrypt("postgresql://demo:demo@fakecorp:5432/fakecorp")
    source.db_type = "postgresql"
    mock_db.session.get.return_value = source

    response = client.get("/internal/data-sources/ds1/connection")

    assert response.status_code == 200
    assert response.json["connection_string"] == "postgresql://demo:demo@fakecorp:5432/fakecorp"


def test_get_connection_internal_not_found(app, client, mock_db):
    mock_db.session.get.return_value = None

    response = client.get("/internal/data-sources/ghost/connection")

    assert response.status_code == 404
