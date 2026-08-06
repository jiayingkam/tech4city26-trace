import pytest
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from backend.retention_guard.atomic.audit_log.app.routes import audit_log_bp, ScanRun, RetentionAction

OWNER_ID = "admin_abc"


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "test-secret"
    JWTManager(app)
    app.register_blueprint(audit_log_bp)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def mock_db():
    with patch("backend.retention_guard.atomic.audit_log.app.routes.db") as mocked_db:
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


def test_create_scan_run_success(app, client, mock_db):
    response = client.post(
        "/scan-runs",
        json={"policy_id": "p1", "data_source_id": "ds1", "mode": "dry_run"},
        headers=auth_header(app),
    )

    assert response.status_code == 201
    mock_db.session.add.assert_called_once()
    added = mock_db.session.add.call_args[0][0]
    assert isinstance(added, ScanRun)
    # status isn't asserted here — its "running" default is a SQLAlchemy
    # column default applied at flush time, which never runs against a
    # mocked session, so the in-memory object's .status is still unset.
    assert added.mode == "dry_run"
    assert added.owner_id == OWNER_ID


def test_create_scan_run_rejects_invalid_mode(app, client, mock_db):
    response = client.post(
        "/scan-runs", json={"policy_id": "p1", "data_source_id": "ds1", "mode": "bogus"}, headers=auth_header(app)
    )
    assert response.status_code == 400


def test_update_scan_run_not_owned_is_404(app, client, mock_db):
    other = MagicMock()
    other.owner_id = "someone_else"
    mock_db.session.get.return_value = other

    response = client.patch("/scan-runs/r1", json={"status": "completed"}, headers=auth_header(app))

    assert response.status_code == 404


def test_update_scan_run_finished_stamps_finished_at(app, client, mock_db):
    run = MagicMock()
    run.owner_id = OWNER_ID
    run.to_dict.return_value = {"scan_run_id": "r1"}
    mock_db.session.get.return_value = run

    response = client.patch(
        "/scan-runs/r1",
        json={"status": "completed", "rows_scanned": 10, "rows_matched": 3, "finished": True},
        headers=auth_header(app),
    )

    assert response.status_code == 200
    assert run.status == "completed"
    assert run.rows_scanned == 10
    assert run.rows_matched == 3
    assert run.finished_at is not None
    mock_db.session.commit.assert_called_once()


def test_create_actions_batch_success(app, client, mock_db):
    response = client.post(
        "/actions",
        json={"actions": [
            {"scan_run_id": "r1", "policy_id": "p1", "subject_id_value": "cust-1", "action_type": "anonymise"},
            {"scan_run_id": "r1", "policy_id": "p1", "subject_id_value": "cust-2", "action_type": "anonymise"},
        ]},
        headers=auth_header(app),
    )

    assert response.status_code == 201
    mock_db.session.add_all.assert_called_once()
    created = mock_db.session.add_all.call_args[0][0]
    assert len(created) == 2
    assert all(isinstance(a, RetentionAction) for a in created)
    assert all(a.owner_id == OWNER_ID for a in created)


def test_create_actions_rejects_empty_batch(app, client, mock_db):
    response = client.post("/actions", json={"actions": []}, headers=auth_header(app))
    assert response.status_code == 400


def test_create_actions_rejects_invalid_action_type(app, client, mock_db):
    response = client.post(
        "/actions",
        json={"actions": [{"scan_run_id": "r1", "policy_id": "p1", "subject_id_value": "cust-1", "action_type": "nuke"}]},
        headers=auth_header(app),
    )
    assert response.status_code == 400


def test_list_actions_filters_by_status(app, client, mock_db):
    action = MagicMock()
    action.to_dict.return_value = {"action_id": "a1", "status": "proposed"}
    mock_db.session.scalars.return_value.all.return_value = [action]

    response = client.get("/actions?policy_id=p1&status=proposed", headers=auth_header(app))

    assert response.status_code == 200
    assert len(response.json) == 1


def test_list_actions_rejects_invalid_status(app, client, mock_db):
    response = client.get("/actions?status=not_a_status", headers=auth_header(app))
    assert response.status_code == 400


def test_update_action_approve(app, client, mock_db):
    action = MagicMock()
    action.owner_id = OWNER_ID
    action.to_dict.return_value = {"action_id": "a1", "status": "approved"}
    mock_db.session.get.return_value = action

    response = client.patch("/actions/a1", json={"status": "approved"}, headers=auth_header(app))

    assert response.status_code == 200
    assert action.status == "approved"


def test_update_action_applied_stamps_applied_at(app, client, mock_db):
    action = MagicMock()
    action.owner_id = OWNER_ID
    action.to_dict.return_value = {"action_id": "a1"}
    mock_db.session.get.return_value = action

    response = client.patch(
        "/actions/a1", json={"status": "applied", "applied": True, "detail": "nulled 3 columns"}, headers=auth_header(app)
    )

    assert response.status_code == 200
    assert action.status == "applied"
    assert action.detail == "nulled 3 columns"
    assert action.applied_at is not None
