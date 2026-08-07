import pytest
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from backend.retention_guard.atomic.retention_policies.app.routes import retention_policies_bp, RetentionPolicy

OWNER_ID = "admin_abc"


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "test-secret"
    JWTManager(app)
    app.register_blueprint(retention_policies_bp)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def mock_db():
    with patch("backend.retention_guard.atomic.retention_policies.app.routes.db") as mocked_db:
        yield mocked_db


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


def test_create_policy_success(app, client, mock_db):
    response = client.post(
        "/policies",
        json={"data_source_id": "ds1", "table_name": "customers", "inactive_days": 180},
        headers=auth_header(app),
    )

    assert response.status_code == 201
    mock_db.session.add.assert_called_once()
    added = mock_db.session.add.call_args[0][0]
    assert isinstance(added, RetentionPolicy)
    assert added.action == "anonymise"  # default
    assert added.owner_id == OWNER_ID


def test_create_policy_rejects_non_positive_inactive_days(app, client, mock_db):
    response = client.post(
        "/policies",
        json={"data_source_id": "ds1", "table_name": "customers", "inactive_days": 0},
        headers=auth_header(app),
    )
    assert response.status_code == 400
    mock_db.session.add.assert_not_called()


def test_create_policy_rejects_invalid_action(app, client, mock_db):
    response = client.post(
        "/policies",
        json={"data_source_id": "ds1", "table_name": "customers", "inactive_days": 30, "action": "nuke_it"},
        headers=auth_header(app),
    )
    assert response.status_code == 400


def test_get_policy_not_owned_is_404(app, client, mock_db):
    other = MagicMock()
    other.owner_id = "someone_else"
    mock_db.session.get.return_value = other

    response = client.get("/policies/p1", headers=auth_header(app))

    assert response.status_code == 404


def test_update_policy_changing_schedule_resets_next_scan_due_at(app, client, mock_db):
    policy = MagicMock()
    policy.owner_id = OWNER_ID
    policy.to_dict.return_value = {"policy_id": "p1"}
    mock_db.session.get.return_value = policy

    response = client.patch("/policies/p1", json={"schedule_interval_minutes": 60}, headers=auth_header(app))

    assert response.status_code == 200
    assert policy.schedule_interval_minutes == 60
    assert policy.next_scan_due_at is None
    mock_db.session.commit.assert_called_once()


def test_delete_policy_success(app, client, mock_db):
    policy = MagicMock()
    policy.owner_id = OWNER_ID
    mock_db.session.get.return_value = policy

    response = client.delete("/policies/p1", headers=auth_header(app))

    assert response.status_code == 204
    mock_db.session.delete.assert_called_once_with(policy)


def test_list_due_policies_internal(client, mock_db):
    due_policy = MagicMock()
    due_policy.to_dict.return_value = {"policy_id": "p1", "enabled": True}
    mock_db.session.scalars.return_value.all.return_value = [due_policy]

    response = client.get("/internal/policies/due")

    assert response.status_code == 200
    assert len(response.json) == 1


def test_claim_policy_internal_wins_claim(client, mock_db):
    policy = MagicMock()
    policy.schedule_interval_minutes = 60
    mock_db.session.get.return_value = policy
    mock_db.session.execute.return_value.rowcount = 1
    mock_db.session.refresh.side_effect = lambda p: None
    policy.to_dict.return_value = {"policy_id": "p1"}

    response = client.patch("/internal/policies/p1/claim")

    assert response.status_code == 200
    assert response.json["claimed"] is True


def test_claim_policy_internal_loses_claim(client, mock_db):
    policy = MagicMock()
    policy.schedule_interval_minutes = 60
    mock_db.session.get.return_value = policy
    mock_db.session.execute.return_value.rowcount = 0
    policy.to_dict.return_value = {"policy_id": "p1"}

    response = client.patch("/internal/policies/p1/claim")

    assert response.status_code == 200
    assert response.json["claimed"] is False


def test_claim_policy_internal_not_found(client, mock_db):
    mock_db.session.get.return_value = None

    response = client.patch("/internal/policies/ghost/claim")

    assert response.status_code == 404
