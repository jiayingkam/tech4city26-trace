from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from flask_jwt_extended import create_access_token

from backend.composite.generate_teachable_moment.app.routes import bp
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


def _mock_response(status_code, payload):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


def test_teachable_moment_requires_auth(client):
    response = client.post("/drafts/draft_1/teachable-moment")

    assert response.status_code == 401


def test_teachable_moment_returns_safe_lesson_when_no_detections(client, auth_headers):
    with patch("backend.composite.generate_teachable_moment.app.routes.requests") as mocked_requests:
        mocked_requests.get.return_value = _mock_response(200, [])

        response = client.post("/drafts/draft_1/teachable-moment", headers=auth_headers)

    assert response.status_code == 200
    assert response.json["title"] == "Looks safe to share"
    assert response.json["category"] is None


def test_teachable_moment_uses_highest_risk_detection(client, auth_headers):
    detections = [
        {
            "detection_id": "d1",
            "category": "contact",
            "source_type": "text",
            "exposure_score": 2,
            "detail": "phone number in caption",
        },
        {
            "detection_id": "d2",
            "category": "location",
            "source_type": "image",
            "exposure_score": 4,
            "detail": "block number visible",
        },
    ]
    with patch("backend.composite.generate_teachable_moment.app.routes.requests") as mocked_requests:
        mocked_requests.get.return_value = _mock_response(200, detections)

        response = client.post("/drafts/draft_1/teachable-moment", headers=auth_headers)

    assert response.status_code == 200
    assert response.json["category"] == "location"
    assert response.json["exposure_score"] == 4
    assert response.json["detail"] == "block number visible"
    assert "narrow down" in response.json["explanation"]


def test_teachable_moment_forwards_auth_header(client, auth_headers):
    with patch("backend.composite.generate_teachable_moment.app.routes.requests") as mocked_requests:
        mocked_requests.get.return_value = _mock_response(200, [])

        client.post("/drafts/draft_1/teachable-moment", headers=auth_headers)

    assert mocked_requests.get.call_args.kwargs["headers"] == auth_headers


def test_teachable_moment_handles_detection_service_failure(client, auth_headers):
    with patch("backend.composite.generate_teachable_moment.app.routes.requests") as mocked_requests:
        mocked_requests.get.return_value = _mock_response(500, {"error": "boom"})

        response = client.post("/drafts/draft_1/teachable-moment", headers=auth_headers)

    assert response.status_code == 502
    assert response.json["error"] == "failed to fetch detections"
