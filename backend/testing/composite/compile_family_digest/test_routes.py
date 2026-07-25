from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from flask_jwt_extended import create_access_token

from backend.composite.compile_family_digest.app.routes import bp
from backend.shared.trace_auth import init_auth

USER_ID = "user_abc"


@pytest.fixture
def app():
    app = Flask(__name__)
    with patch.dict("os.environ", {"JWT_SECRET_KEY": "test-secret"}):
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


def _resp(status_code, json_body=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body
    return response


def _fake_get(profile_rows):
    def fake_get(url, params=None, headers=None, timeout=None):
        if url.endswith("/me"):
            return _resp(200, {"user_id": USER_ID, "email": "user@example.com"})
        if url.endswith(f"/users/{USER_ID}/exposure-profiles"):
            assert "window_start" in params
            assert "window_end" in params
            start = datetime.fromisoformat(params["window_start"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(params["window_end"].replace("Z", "+00:00"))
            assert 6.99 < (end - start).total_seconds() / 86400 < 7.01
            return _resp(200, profile_rows)
        raise AssertionError(f"unexpected GET {url}")

    return fake_get


def test_generate_digest_requires_auth(client):
    response = client.post("/digest/generate")

    assert response.status_code == 401


def test_generate_digest_sends_no_activity_email(client, auth_headers):
    sent_payloads = []

    def fake_post(url, json=None, headers=None, timeout=None):
        sent_payloads.append(json)
        return _resp(202)

    with patch.dict(
        "os.environ",
        {"OPENAI_API_KEY": "", "RESEND_API_KEY": "re_test", "RESEND_FROM_EMAIL": "Trace <trace@example.com>"},
        clear=False,
    ), patch("backend.composite.compile_family_digest.app.routes.requests") as mocked_requests:
        mocked_requests.get.side_effect = _fake_get([])
        mocked_requests.post.side_effect = fake_post

        response = client.post("/digest/generate", headers=auth_headers)

    assert response.status_code == 200
    assert response.json["status"] == "sent"
    assert response.json["total_flags"] == 0
    assert sent_payloads[0]["to"] == ["user@example.com"]
    assert sent_payloads[0]["from"] == "Trace <trace@example.com>"
    assert "no notable activity" in sent_payloads[0]["html"].lower()


def test_generate_digest_aggregates_profile_rows_only(client, auth_headers):
    profile_rows = [
        {
            "category_breakdown": {
                "face": 1,
                "location": 2,
                "document": 0,
                "metadata": 1,
                "contact": 0,
                "financial": 0,
            },
            "privacy_health_score": 82,
            "window_start": "2026-07-14T00:00:00Z",
            "window_end": "2026-07-15T00:00:00Z",
        },
        {
            "category_breakdown": {
                "face": 0,
                "location": 1,
                "document": 1,
                "metadata": 0,
                "contact": 2,
                "financial": 0,
            },
            "privacy_health_score": 76,
            "window_start": "2026-07-15T00:00:00Z",
            "window_end": "2026-07-16T00:00:00Z",
        },
    ]
    sent_payloads = []

    def fake_post(url, json=None, headers=None, timeout=None):
        sent_payloads.append(json)
        return _resp(202)

    with patch.dict(
        "os.environ",
        {"OPENAI_API_KEY": "", "RESEND_API_KEY": "re_test", "RESEND_FROM_EMAIL": "Trace <trace@example.com>"},
        clear=False,
    ), patch("backend.composite.compile_family_digest.app.routes.requests") as mocked_requests:
        mocked_requests.get.side_effect = _fake_get(profile_rows)
        mocked_requests.post.side_effect = fake_post

        response = client.post("/digest/generate", headers=auth_headers)

    assert response.status_code == 200
    assert response.json["total_flags"] == 8
    html = sent_payloads[0]["html"]
    assert "Face" in html
    assert "Contact" in html
    get_urls = [call.args[0] for call in mocked_requests.get.call_args_list]
    assert all("/detections" not in url and "/drafts" not in url for url in get_urls)


def test_generate_digest_returns_503_when_resend_unconfigured(client, auth_headers):
    with patch.dict(
        "os.environ",
        {"OPENAI_API_KEY": "", "RESEND_API_KEY": "", "RESEND_FROM_EMAIL": ""},
        clear=False,
    ), patch(
        "backend.composite.compile_family_digest.app.routes.requests"
    ) as mocked_requests:
        mocked_requests.get.side_effect = _fake_get([])

        response = client.post("/digest/generate", headers=auth_headers)

    assert response.status_code == 503
    assert response.json["error"] == "resend is not configured"
