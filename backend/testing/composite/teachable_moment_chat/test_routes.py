from unittest.mock import patch

import pytest
from flask import Flask
from flask_jwt_extended import create_access_token

from backend.composite.teachable_moment_chat.app.agent import ChatError
from backend.composite.teachable_moment_chat.app.routes import bp
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


def test_chat_requires_auth(client):
    response = client.post("/drafts/draft_1/chat", json={"message": "why was this flagged?"})

    assert response.status_code == 401


def test_chat_requires_message(client, auth_headers):
    response = client.post("/drafts/draft_1/chat", json={}, headers=auth_headers)

    assert response.status_code == 400


def test_chat_returns_agent_reply(client, auth_headers):
    with patch("backend.composite.teachable_moment_chat.app.routes.answer") as mocked_answer:
        mocked_answer.return_value = "That phone number could let a stranger contact you directly."

        response = client.post(
            "/drafts/draft_1/chat",
            json={"message": "why was this flagged?", "history": []},
            headers=auth_headers,
        )

    assert response.status_code == 200
    assert response.json["reply"] == "That phone number could let a stranger contact you directly."
    kwargs = mocked_answer.call_args.kwargs
    assert kwargs["draft_id"] == "draft_1"
    assert kwargs["message"] == "why was this flagged?"
    assert kwargs["owner_id"] == USER_ID
    assert kwargs["auth_headers"] == auth_headers


def test_chat_forwards_history(client, auth_headers):
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    with patch("backend.composite.teachable_moment_chat.app.routes.answer") as mocked_answer:
        mocked_answer.return_value = "ok"

        client.post(
            "/drafts/draft_1/chat",
            json={"message": "next question", "history": history},
            headers=auth_headers,
        )

    assert mocked_answer.call_args.kwargs["history"] == history


def test_chat_handles_agent_failure(client, auth_headers):
    with patch("backend.composite.teachable_moment_chat.app.routes.answer") as mocked_answer:
        mocked_answer.side_effect = ChatError("agent invocation failed")

        response = client.post(
            "/drafts/draft_1/chat",
            json={"message": "why was this flagged?"},
            headers=auth_headers,
        )

    assert response.status_code == 502
    assert response.json["error"] == "failed to generate a reply"


def test_health_is_unauthenticated(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json["status"] == "ok"
