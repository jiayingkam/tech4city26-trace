import sys
import types
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from flask_jwt_extended import create_access_token

from backend.composite.compile_family_digest.app.routes import (
    bp,
    _build_llm_digest_prompt,
    _build_digest_summary,
    _format_date_range,
    _generate_digest_copy,
    _llm_digest_input,
)
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


def _fake_get(weekly_digest):
    def fake_get(url, params=None, headers=None, timeout=None):
        if url.endswith("/me"):
            return _resp(200, {"user_id": USER_ID, "email": "user@example.com"})
        if url.endswith(f"/users/{USER_ID}/profile"):
            return _resp(200, {"user_id": USER_ID, "profile": {"weekly_digest": weekly_digest}})
        raise AssertionError(f"unexpected GET {url}")

    return fake_get


def test_generate_digest_requires_auth(client):
    response = client.post("/digest/generate")

    assert response.status_code == 401


def test_format_date_range_is_email_friendly():
    assert _format_date_range(
        datetime(2026, 7, 18, 12, 30, tzinfo=timezone.utc),
        datetime(2026, 7, 25, 12, 30, tzinfo=timezone.utc),
    ) == "18 Jul – 25 Jul 2026"
    assert _format_date_range(
        datetime(2025, 12, 28, 12, 30, tzinfo=timezone.utc),
        datetime(2026, 1, 4, 12, 30, tzinfo=timezone.utc),
    ) == "28 Dec 2025 – 04 Jan 2026"


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
        mocked_requests.get.side_effect = _fake_get(None)
        mocked_requests.post.side_effect = fake_post

        response = client.post("/digest/generate", headers=auth_headers)

    assert response.status_code == 200
    assert response.json["status"] == "sent"
    assert response.json["total_flags"] == 0
    assert sent_payloads[0]["to"] == ["user@example.com"]
    assert sent_payloads[0]["from"] == "Trace <trace@example.com>"
    html = sent_payloads[0]["html"]
    assert "Hey there! Your Trace Weekly Digest is here!" in html
    assert "100/100" in html
    assert "Great week" in html
    assert "What Trace noticed this week" in html
    assert "The bigger picture" in html
    assert "Let's talk about it" in html


def test_generate_digest_uses_stored_weekly_digest_only(client, auth_headers):
    weekly_digest = {
        "category_breakdown": {
            "face": 1,
            "location": 3,
            "document": 1,
            "metadata": 1,
            "contact": 2,
            "financial": 0,
        },
        "privacy_health_score": 76,
        "window_start": "2026-07-14T00:00:00Z",
        "window_end": "2026-07-21T00:00:00Z",
        "specific_findings": [
            {
                "category": "location",
                "source_type": "image",
                "exposure_score": 4,
                "detail": "school sign in the background",
            }
        ],
    }
    sent_payloads = []

    def fake_post(url, json=None, headers=None, timeout=None):
        sent_payloads.append(json)
        return _resp(202)

    with patch.dict(
        "os.environ",
        {"OPENAI_API_KEY": "", "RESEND_API_KEY": "re_test", "RESEND_FROM_EMAIL": "Trace <trace@example.com>"},
        clear=False,
    ), patch("backend.composite.compile_family_digest.app.routes.requests") as mocked_requests:
        mocked_requests.get.side_effect = _fake_get(weekly_digest)
        mocked_requests.post.side_effect = fake_post

        response = client.post("/digest/generate", headers=auth_headers)

    assert response.status_code == 200
    assert response.json["total_flags"] == 8
    html = sent_payloads[0]["html"]
    assert "Face" in html
    assert "Contact" in html
    assert "Financial" not in html
    assert "school sign in the background" not in html
    assert "76/100" in html
    assert "Decent week" in html
    assert "A few posts" in html or "A number of posts" in html
    assert "What Trace noticed this week" in html
    assert "The bigger picture" in html
    assert "Let's talk about it" in html
    get_urls = [call.args[0] for call in mocked_requests.get.call_args_list]
    assert all("/detections" not in url and "/drafts" not in url for url in get_urls)


def test_generate_digest_copy_falls_back_when_llm_fails():
    class FailingStructuredLlm:
        def invoke(self, messages):
            raise RuntimeError("bad schema")

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            pass

        def with_structured_output(self, model, method=None):
            assert method == "function_calling"
            return FailingStructuredLlm()

    fake_langchain_openai = types.SimpleNamespace(ChatOpenAI=FakeChatOpenAI)
    summary = {
        "has_activity": True,
        "total_flags": 2,
        "active_category_breakdown": {"location": 2},
        "latest_privacy_health_score": 90,
    }

    with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False), patch.dict(
        sys.modules, {"langchain_openai": fake_langchain_openai}
    ):
        copy = _generate_digest_copy(summary)

    assert copy["headline"] == "Hey there! Your Trace Weekly Digest is here! 🔍"
    assert copy["score_section"]["score"] == 90
    assert copy["category_breakdown"]["location"]


def test_llm_digest_input_prebuilds_prompt_structure():
    summary = _build_digest_summary(
        [{
            "category_breakdown": {
                "face": 0,
                "location": 3,
                "document": 0,
                "metadata": 0,
                "contact": 0,
                "financial": 0,
                "credentials": 1,
            },
            "privacy_health_score": 35,
            "window_start": "2026-07-18T00:00:00Z",
            "window_end": "2026-07-25T00:00:00Z",
        }],
        datetime(2026, 7, 18, 12, 30, tzinfo=timezone.utc),
        datetime(2026, 7, 25, 12, 30, tzinfo=timezone.utc),
    )

    prompt_input = _llm_digest_input(summary)

    assert prompt_input["active_categories"] == {"location": 3, "credentials": 1}
    assert prompt_input["category_emoji"]["credentials"] == "🔑"
    assert prompt_input["category_meaning"]["location"].startswith("help someone figure out")
    assert prompt_input["category_lines"]["location"].startswith("📍 Location: A number of posts")
    assert prompt_input["score_label"] == "Tough week — a good one to reflect on together 💬"
    assert prompt_input["top_category"] == "location"


def test_llm_digest_prompt_only_asks_for_score_explanation_and_prompts():
    summary = _build_digest_summary(
        [{
            "category_breakdown": {
                "face": 0,
                "location": 3,
                "document": 0,
                "metadata": 0,
                "contact": 0,
                "financial": 0,
                "credentials": 0,
            },
            "privacy_health_score": 35,
            "window_start": "2026-07-18T00:00:00Z",
            "window_end": "2026-07-25T00:00:00Z",
        }],
        datetime(2026, 7, 18, 12, 30, tzinfo=timezone.utc),
        datetime(2026, 7, 25, 12, 30, tzinfo=timezone.utc),
    )

    prompt = _build_llm_digest_prompt(summary)

    assert "FIXED DATA" in prompt
    assert "Category breakdown (already written — copy exactly):" in prompt
    assert "YOUR JOB — write only these two sections" in prompt
    assert "SCORE_EXPLANATION" in prompt
    assert "DISCUSSION_PROMPTS" in prompt
    assert '"score_explanation"' in prompt
    assert '"discussion_prompts"' in prompt
    assert 'Do NOT start with "How do you feel about"' in prompt
    assert "📍 Location: A number of posts" in prompt


def test_generate_digest_returns_503_when_resend_unconfigured(client, auth_headers):
    with patch.dict(
        "os.environ",
        {"OPENAI_API_KEY": "", "RESEND_API_KEY": "", "RESEND_FROM_EMAIL": ""},
        clear=False,
    ), patch(
        "backend.composite.compile_family_digest.app.routes.requests"
    ) as mocked_requests:
        mocked_requests.get.side_effect = _fake_get(None)

        response = client.post("/digest/generate", headers=auth_headers)

    assert response.status_code == 503
    assert response.json["error"] == "resend is not configured"
