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


def _draft(draft_id, captured_at, content_type="image", storage_path="x.jpg", text_content=None):
    return {
        "draft_id": draft_id,
        "captured_at": captured_at,
        "content_type": content_type,
        "storage_path": storage_path,
        "text_content": text_content,
    }


def _history_fake_get(drafts, detections_by_draft=None, quarantine_by_draft=None):
    detections_by_draft = detections_by_draft or {}
    quarantine_by_draft = quarantine_by_draft or {}

    def fake_get(url, headers=None, params=None):
        if url.endswith("/users/user_abc/drafts"):
            return _resp(200, drafts)
        for draft_id, dets in detections_by_draft.items():
            if url.endswith(f"/drafts/{draft_id}/detections"):
                return _resp(200, dets)
        for draft_id, items in quarantine_by_draft.items():
            if url.endswith(f"/drafts/{draft_id}/quarantine"):
                return _resp(200, items)
        # any draft not explicitly given detections/quarantine has neither
        if "/detections" in url or "/quarantine" in url:
            return _resp(200, [])
        raise AssertionError(f"unexpected GET {url}")

    return fake_get


def test_get_history_merges_and_sorts_across_drafts(client, auth_headers, mock_requests):
    drafts = [_draft("d1", "2026-01-01T00:00:00+00:00"), _draft("d2", "2026-02-01T00:00:00+00:00")]
    mock_requests.get.side_effect = _history_fake_get(drafts)

    response = client.get("/history", headers=auth_headers)

    assert response.status_code == 200
    ids = [p["draft_id"] for p in response.json]
    assert ids == ["d2", "d1"]  # newest first


def test_get_history_derives_accepted_status(client, auth_headers, mock_requests):
    drafts = [_draft("d1", "2026-01-01T00:00:00+00:00")]
    detections = [{"category": "face", "resolution": "accepted"}]
    mock_requests.get.side_effect = _history_fake_get(drafts, {"d1": detections})

    response = client.get("/history", headers=auth_headers)

    assert response.status_code == 200
    assert response.json[0]["status"] == "accepted"


def test_get_history_derives_rejected_status(client, auth_headers, mock_requests):
    drafts = [_draft("d1", "2026-01-01T00:00:00+00:00")]
    detections = [
        {"category": "face", "resolution": "accepted"},
        {"category": "document", "resolution": "rejected"},
    ]
    mock_requests.get.side_effect = _history_fake_get(drafts, {"d1": detections})

    response = client.get("/history", headers=auth_headers)

    assert response.json[0]["status"] == "rejected"


def test_get_history_derives_pending_status(client, auth_headers, mock_requests):
    drafts = [_draft("d1", "2026-01-01T00:00:00+00:00")]
    detections = [{"category": "face", "resolution": None}]
    mock_requests.get.side_effect = _history_fake_get(drafts, {"d1": detections})

    response = client.get("/history", headers=auth_headers)

    assert response.json[0]["status"] == "pending"


def test_get_history_derives_quarantined_status_with_cooldown(client, auth_headers, mock_requests):
    drafts = [_draft("d1", "2026-01-01T00:00:00+00:00")]
    quarantine = [{"quarantine_id": "q1", "state": "held", "cooldown_expiry": "2026-01-01T01:00:00+00:00"}]
    mock_requests.get.side_effect = _history_fake_get(drafts, quarantine_by_draft={"d1": quarantine})

    response = client.get("/history", headers=auth_headers)

    assert response.json[0]["status"] == "quarantined"
    assert response.json[0]["cooldown_expiry"] == "2026-01-01T01:00:00+00:00"


def test_get_history_filters_by_status(client, auth_headers, mock_requests):
    drafts = [_draft("d1", "2026-01-01T00:00:00+00:00"), _draft("d2", "2026-01-02T00:00:00+00:00")]
    detections_by_draft = {
        "d1": [{"category": "face", "resolution": "accepted"}],
        "d2": [{"category": "face", "resolution": "rejected"}],
    }
    mock_requests.get.side_effect = _history_fake_get(drafts, detections_by_draft)

    response = client.get("/history?filter=accepted", headers=auth_headers)

    assert response.status_code == 200
    assert [p["draft_id"] for p in response.json] == ["d1"]


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
