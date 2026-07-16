import pytest
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import create_access_token

from backend.composite.manage_history.app.routes import bp
from backend.shared.trace_auth import init_auth

USER_ID = "user_abc"
INTERNAL_KEY = "test-internal-key"


@pytest.fixture
def app():
    app = Flask(__name__)
    # INTERNAL_API_KEY has to be set before init_auth runs — it captures the
    # value once via closure, so patching os.environ later (e.g. inside a
    # test body) is too late to affect the already-registered hook.
    with patch.dict("os.environ", {"JWT_SECRET_KEY": "test-secret", "INTERNAL_API_KEY": INTERNAL_KEY}):
        init_auth(app)
    app.register_blueprint(bp)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_headers(app):
    with app.app_context():
        token = create_access_token(identity=USER_ID)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def mock_requests():
    with patch("backend.composite.manage_history.app.routes.requests") as mocked:
        yield mocked


def _resp(status_code, json_body=None):
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_body
    return m


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200


def test_get_history_requires_auth(client):
    response = client.get("/history")
    assert response.status_code == 401


def test_get_history_invalid_filter(client, auth_headers):
    response = client.get("/history?filter=bogus", headers=auth_headers)
    assert response.status_code == 400


def test_get_history_merges_and_sorts_across_drafts(client, auth_headers, mock_requests):
    drafts = [{"draft_id": "d1"}, {"draft_id": "d2"}]
    d1_detections = [{"detection_id": "a", "created_at": "2026-01-01T00:00:00+00:00", "resolution": None}]
    d2_detections = [{"detection_id": "b", "created_at": "2026-02-01T00:00:00+00:00", "resolution": "accepted"}]

    def fake_get(url, headers=None, params=None):
        if url.endswith("/users/user_abc/drafts"):
            return _resp(200, drafts)
        if url.endswith("/drafts/d1/detections"):
            return _resp(200, d1_detections)
        if url.endswith("/drafts/d2/detections"):
            return _resp(200, d2_detections)
        raise AssertionError(f"unexpected GET {url}")

    mock_requests.get.side_effect = fake_get

    response = client.get("/history", headers=auth_headers)

    assert response.status_code == 200
    ids = [d["detection_id"] for d in response.json]
    assert ids == ["b", "a"]  # newest first


def test_get_history_filters_by_resolution(client, auth_headers, mock_requests):
    drafts = [{"draft_id": "d1"}]
    detections = [
        {"detection_id": "a", "created_at": "2026-01-01T00:00:00+00:00", "resolution": "accepted"},
        {"detection_id": "b", "created_at": "2026-01-02T00:00:00+00:00", "resolution": "rejected"},
    ]

    def fake_get(url, headers=None, params=None):
        if url.endswith("/users/user_abc/drafts"):
            return _resp(200, drafts)
        if url.endswith("/drafts/d1/detections"):
            return _resp(200, detections)
        raise AssertionError(f"unexpected GET {url}")

    mock_requests.get.side_effect = fake_get

    response = client.get("/history?filter=accepted", headers=auth_headers)

    assert response.status_code == 200
    assert [d["detection_id"] for d in response.json] == ["a"]


def test_get_history_quarantine_merges_across_drafts(client, auth_headers, mock_requests):
    drafts = [{"draft_id": "d1"}]
    items = [{"quarantine_id": "q1", "created_at": "2026-01-01T00:00:00+00:00"}]

    def fake_get(url, headers=None, params=None):
        if url.endswith("/users/user_abc/drafts"):
            return _resp(200, drafts)
        if url.endswith("/drafts/d1/quarantine"):
            return _resp(200, items)
        raise AssertionError(f"unexpected GET {url}")

    mock_requests.get.side_effect = fake_get

    response = client.get("/history/quarantine", headers=auth_headers)

    assert response.status_code == 200
    assert response.json[0]["quarantine_id"] == "q1"


def test_delete_history_requires_at_least_one_id(client, auth_headers, mock_requests):
    response = client.post("/history/delete", json={}, headers=auth_headers)
    assert response.status_code == 400


def test_delete_history_cascades_a_draft(client, auth_headers, mock_requests):
    mock_requests.delete.return_value = _resp(204)

    response = client.post("/history/delete", json={"draft_ids": ["d1"]}, headers=auth_headers)

    assert response.status_code == 200
    assert response.json["draft_ids"]["d1"] == "deleted"
    deleted_urls = [call.args[0] for call in mock_requests.delete.call_args_list]
    assert any("/drafts/d1/detections" in u for u in deleted_urls)
    assert any("/drafts/d1/edits" in u for u in deleted_urls)
    assert any("/drafts/d1/quarantine" in u for u in deleted_urls)
    assert any("/drafts/d1/original" in u for u in deleted_urls)
    assert any("/drafts/d1/remediated" in u for u in deleted_urls)
    assert any(u.endswith("/drafts/d1") for u in deleted_urls)


def test_delete_history_individual_detection_and_quarantine(client, auth_headers, mock_requests):
    mock_requests.delete.return_value = _resp(204)

    response = client.post(
        "/history/delete",
        json={"detection_ids": ["det1"], "quarantine_ids": ["q1"]},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json["detection_ids"]["det1"] == "deleted"
    assert response.json["quarantine_ids"]["q1"] == "deleted"


def test_delete_history_reports_failure_without_blocking_others(client, auth_headers, mock_requests):
    mock_requests.delete.return_value = _resp(403)

    response = client.post("/history/delete", json={"detection_ids": ["not_mine"]}, headers=auth_headers)

    assert response.status_code == 200
    assert response.json["detection_ids"]["not_mine"] == "failed"


def test_sweep_expired_requires_internal_key(client):
    response = client.post("/internal/sweep-expired")
    assert response.status_code == 401


def test_sweep_expired_only_deletes_drafts_past_the_window(client, mock_requests):
    # The module-level INTERNAL_API_KEY (read once at import time, used when
    # this service calls out to users) needs patching separately from the
    # app fixture's hook, which only guards *incoming* requests to this service.
    with patch("backend.composite.manage_history.app.routes.INTERNAL_API_KEY", INTERNAL_KEY):

        old_draft = {"draft_id": "old", "captured_at": "2020-01-01T00:00:00+00:00"}
        new_draft = {"draft_id": "new", "captured_at": "2099-01-01T00:00:00+00:00"}

        def fake_get(url, headers=None, params=None):
            if url.endswith("/internal/users"):
                return _resp(200, [{"user_id": USER_ID, "retention_mode": "auto_expire"}])
            if url.endswith(f"/users/{USER_ID}/drafts"):
                return _resp(200, [old_draft, new_draft])
            raise AssertionError(f"unexpected GET {url}")

        def fake_post(url, json=None, headers=None):
            if url.endswith("/internal/impersonate"):
                return _resp(200, {"token": "impersonated-token"})
            raise AssertionError(f"unexpected POST {url}")

        mock_requests.get.side_effect = fake_get
        mock_requests.post.side_effect = fake_post
        mock_requests.delete.return_value = _resp(204)

        response = client.post("/internal/sweep-expired", headers={"X-Internal-Key": INTERNAL_KEY})

        assert response.status_code == 200
        assert response.json["swept_draft_ids"] == ["old"]
