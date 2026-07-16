import pytest
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import create_access_token

from backend.atomic.detections.app.routes import detections_bp, Detection
from backend.shared.trace_auth import init_auth

USER_ID = "user_abc"


@pytest.fixture
def app():
    app = Flask(__name__)
    with patch.dict("os.environ", {"JWT_SECRET_KEY": "test-secret"}):
        init_auth(app)
    app.register_blueprint(detections_bp)
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
def mock_db():
    with patch("backend.atomic.detections.app.routes.db") as mocked_db:
        yield mocked_db


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200


def test_create_detection_requires_auth(client):
    response = client.post(
        "/detections",
        json={"draft_id": "draft_1", "category": "face", "source_type": "image", "exposure_score": 3},
    )
    assert response.status_code == 401


def test_create_detection_stamps_owner_from_token(client, mock_db, auth_headers):
    with patch("backend.atomic.detections.app.routes.Detection") as MockDetection:
        mock_instance = MagicMock()
        mock_instance.to_dict.return_value = {"detection_id": "d1", "owner_id": USER_ID}
        MockDetection.return_value = mock_instance

        response = client.post(
            "/detections",
            json={
                "draft_id": "draft_1",
                "category": "face",
                "source_type": "image",
                "exposure_score": 3,
                # even if a client tried to set owner_id explicitly, it's ignored
                "owner_id": "someone_else",
            },
            headers=auth_headers,
        )

        assert response.status_code == 201
        assert MockDetection.call_args.kwargs["owner_id"] == USER_ID
        mock_db.session.add.assert_called_once_with(mock_instance)


def test_list_detections_filters_by_owner(client, mock_db, auth_headers):
    mock_db.session.scalars.return_value.all.return_value = []

    response = client.get("/drafts/draft_1/detections", headers=auth_headers)

    assert response.status_code == 200
    assert response.json == []
    # filter_by should be called with both draft_id and the token's owner_id
    args, kwargs = mock_db.select.return_value.filter_by.call_args
    assert kwargs == {"draft_id": "draft_1", "owner_id": USER_ID}


def test_get_detection_forbidden_for_other_owner(client, mock_db, auth_headers):
    mock_detection = MagicMock()
    mock_detection.owner_id = "someone_else"
    mock_db.session.get.return_value = mock_detection

    response = client.get("/detections/d1", headers=auth_headers)

    assert response.status_code == 403


def test_update_detection_sets_resolution(client, mock_db, auth_headers):
    mock_detection = MagicMock()
    mock_detection.owner_id = USER_ID
    mock_detection.to_dict.return_value = {"detection_id": "d1", "resolution": "accepted"}
    mock_db.session.get.return_value = mock_detection

    response = client.patch("/detections/d1", json={"resolution": "accepted"}, headers=auth_headers)

    assert response.status_code == 200
    assert mock_detection.resolution == "accepted"
    mock_db.session.commit.assert_called_once()


def test_update_detection_invalid_resolution(client, mock_db, auth_headers):
    mock_detection = MagicMock()
    mock_detection.owner_id = USER_ID
    mock_db.session.get.return_value = mock_detection

    response = client.patch("/detections/d1", json={"resolution": "maybe"}, headers=auth_headers)

    assert response.status_code == 400
    mock_db.session.commit.assert_not_called()


def test_update_detection_clears_resolution_with_null(client, mock_db, auth_headers):
    mock_detection = MagicMock()
    mock_detection.owner_id = USER_ID
    mock_detection.to_dict.return_value = {"detection_id": "d1", "resolution": None}
    mock_db.session.get.return_value = mock_detection

    response = client.patch("/detections/d1", json={"resolution": None}, headers=auth_headers)

    assert response.status_code == 200
    assert mock_detection.resolution is None


def test_update_detection_no_fields(client, mock_db, auth_headers):
    mock_detection = MagicMock()
    mock_detection.owner_id = USER_ID
    mock_db.session.get.return_value = mock_detection

    response = client.patch("/detections/d1", json={}, headers=auth_headers)

    assert response.status_code == 400
    mock_db.session.commit.assert_not_called()


def test_delete_detection_forbidden_for_other_owner(client, mock_db, auth_headers):
    mock_detection = MagicMock()
    mock_detection.owner_id = "someone_else"
    mock_db.session.get.return_value = mock_detection

    response = client.delete("/detections/d1", headers=auth_headers)

    assert response.status_code == 403
    mock_db.session.delete.assert_not_called()


def test_delete_detections_for_draft_bulk(client, mock_db, auth_headers):
    mock_d1, mock_d2 = MagicMock(), MagicMock()
    mock_db.session.scalars.return_value.all.return_value = [mock_d1, mock_d2]

    response = client.delete("/drafts/draft_1/detections", headers=auth_headers)

    assert response.status_code == 204
    assert mock_db.session.delete.call_count == 2
    mock_db.session.commit.assert_called_once()
