# Running these tests requires this service's own dependencies installed
# (in particular `holehe`, `trio`, `httpx` — see
# backend/composite/check_breach_exposure/requirements.txt), the same way
# any other composite service's tests would need its requirements.txt
# installed. `check_holehe`/`check_leakcheck` themselves are never exercised
# for real here — every test below mocks them at the routes.py boundary — but
# importing routes.py still imports holehe_check.py, which imports holehe.
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from flask_jwt_extended import create_access_token

from backend.composite.check_breach_exposure.app.routes import bp
from backend.shared.trace_auth import init_auth

USER_ID = "user_abc"
EMAIL = "user@example.com"

LEAKCHECK_OK = {"found": True, "fields": ["password", "username"], "sources": [{"name": "Evony.com", "date": "2016-07"}]}
HOLEHE_OK = {
    "total_attempted": 121,
    "conclusive": [
        {"name": "github", "domain": "github.com", "exists": True},
        {"name": "spotify", "domain": "spotify.com", "exists": False},
    ],
}


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


def _fake_get(stored_profile=None):
    def fake_get(url, headers=None, timeout=None):
        if url.endswith("/me"):
            return _resp(200, {"user_id": USER_ID, "email": EMAIL})
        if url.endswith(f"/users/{USER_ID}/profile"):
            if stored_profile is None:
                return _resp(404)
            return _resp(200, {"user_id": USER_ID, "profile": stored_profile})
        raise AssertionError(f"unexpected GET {url}")

    return fake_get


def test_check_requires_auth(client):
    response = client.post("/breach-exposure/check")

    assert response.status_code == 401


def test_check_runs_both_checkers_on_a_fresh_request(client, auth_headers):
    put_calls = []

    def fake_put(url, json=None, headers=None, timeout=None):
        put_calls.append(json)
        return _resp(200, {"user_id": USER_ID, "profile": json["profile"]})

    with patch("backend.composite.check_breach_exposure.app.routes.requests") as mocked_requests, \
         patch("backend.composite.check_breach_exposure.app.routes.check_leakcheck") as mocked_leakcheck, \
         patch("backend.composite.check_breach_exposure.app.routes.check_holehe") as mocked_holehe:
        mocked_requests.get.side_effect = _fake_get(stored_profile=None)
        mocked_requests.put.side_effect = fake_put
        mocked_leakcheck.return_value = LEAKCHECK_OK
        mocked_holehe.return_value = HOLEHE_OK

        response = client.post("/breach-exposure/check", headers=auth_headers)

    assert response.status_code == 200
    body = response.json
    assert body["leakcheck"] == {"status": "ok", **LEAKCHECK_OK}
    assert body["holehe"]["status"] == "ok"
    assert body["holehe"]["platforms_attempted"] == 121
    assert body["holehe"]["platforms_conclusive"] == 2
    assert body["holehe"]["registered"] == [HOLEHE_OK["conclusive"][0]]
    mocked_leakcheck.assert_called_once_with(EMAIL)
    mocked_holehe.assert_called_once_with(EMAIL)
    # Result was persisted into the exposure profile, not just returned.
    assert put_calls[0]["profile"]["breach_exposure"]["leakcheck"]["found"] is True


def test_check_leakcheck_failure_surfaces_as_unavailable_not_clear(client, auth_headers):
    with patch("backend.composite.check_breach_exposure.app.routes.requests") as mocked_requests, \
         patch("backend.composite.check_breach_exposure.app.routes.check_leakcheck") as mocked_leakcheck, \
         patch("backend.composite.check_breach_exposure.app.routes.check_holehe") as mocked_holehe:
        mocked_requests.get.side_effect = _fake_get(stored_profile=None)
        mocked_requests.put.side_effect = lambda *a, **k: _resp(200, {"profile": {}})
        mocked_leakcheck.return_value = None  # simulates a rate-limited/failed call
        mocked_holehe.return_value = HOLEHE_OK

        response = client.post("/breach-exposure/check", headers=auth_headers)

    body = response.json
    assert body["leakcheck"]["status"] == "unavailable"
    assert "found" not in body["leakcheck"]  # never collapsed into a false "not found"


def test_check_holehe_failure_surfaces_as_unavailable_not_clear(client, auth_headers):
    with patch("backend.composite.check_breach_exposure.app.routes.requests") as mocked_requests, \
         patch("backend.composite.check_breach_exposure.app.routes.check_leakcheck") as mocked_leakcheck, \
         patch("backend.composite.check_breach_exposure.app.routes.check_holehe") as mocked_holehe:
        mocked_requests.get.side_effect = _fake_get(stored_profile=None)
        mocked_requests.put.side_effect = lambda *a, **k: _resp(200, {"profile": {}})
        mocked_leakcheck.return_value = LEAKCHECK_OK
        mocked_holehe.return_value = None  # simulates a timed-out scan

        response = client.post("/breach-exposure/check", headers=auth_headers)

    body = response.json
    assert body["holehe"]["status"] == "unavailable"
    assert "registered" not in body["holehe"]


def test_check_always_recomputes_even_with_a_fully_successful_stored_result(client, auth_headers):
    """The check endpoint is deliberately not cached: unlike the mosaic
    exposure profile, an unchanged email doesn't guarantee an unchanged
    breach/registration answer, so an explicit "Check" click must always run
    a real check — even when a fully successful prior result already exists
    for this exact email. (Regression coverage for the earlier fingerprint-
    based caching, which silently replayed stale results — including stale
    failures — instead of ever rechecking.)"""
    previous_result = {
        "email": EMAIL,
        "checked_at": "2026-08-01T00:00:00Z",
        "leakcheck": {"status": "ok", **LEAKCHECK_OK},
        "holehe": {"status": "ok", "platforms_attempted": 121, "platforms_conclusive": 2, "registered": [HOLEHE_OK["conclusive"][0]]},
    }
    stored_profile = {"breach_exposure": previous_result}
    put_calls = []

    def fake_put(url, json=None, headers=None, timeout=None):
        put_calls.append(json)
        return _resp(200, {"user_id": USER_ID, "profile": json["profile"]})

    with patch("backend.composite.check_breach_exposure.app.routes.requests") as mocked_requests, \
         patch("backend.composite.check_breach_exposure.app.routes.check_leakcheck") as mocked_leakcheck, \
         patch("backend.composite.check_breach_exposure.app.routes.check_holehe") as mocked_holehe:
        mocked_requests.get.side_effect = _fake_get(stored_profile=stored_profile)
        mocked_requests.put.side_effect = fake_put
        mocked_leakcheck.return_value = LEAKCHECK_OK
        mocked_holehe.return_value = HOLEHE_OK

        response = client.post("/breach-exposure/check", headers=auth_headers)

    assert response.status_code == 200
    mocked_leakcheck.assert_called_once_with(EMAIL)
    mocked_holehe.assert_called_once_with(EMAIL)
    assert put_calls  # the fresh result was persisted, overwriting the old one


def test_status_requires_auth(client):
    response = client.get("/breach-exposure/status")

    assert response.status_code == 401


def test_status_returns_stored_result_without_calling_either_checker(client, auth_headers):
    stored_profile = {"breach_exposure": {"email": EMAIL, "leakcheck": {"status": "ok", **LEAKCHECK_OK}}}

    with patch("backend.composite.check_breach_exposure.app.routes.requests") as mocked_requests, \
         patch("backend.composite.check_breach_exposure.app.routes.check_leakcheck") as mocked_leakcheck, \
         patch("backend.composite.check_breach_exposure.app.routes.check_holehe") as mocked_holehe:
        mocked_requests.get.side_effect = _fake_get(stored_profile=stored_profile)

        response = client.get("/breach-exposure/status", headers=auth_headers)

    assert response.status_code == 200
    assert response.json == stored_profile["breach_exposure"]
    mocked_leakcheck.assert_not_called()
    mocked_holehe.assert_not_called()


def test_health_is_public():
    app = Flask(__name__)
    with patch.dict("os.environ", {"JWT_SECRET_KEY": "test-secret"}):
        init_auth(app)
    app.register_blueprint(bp)
    client = app.test_client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json == {"status": "ok"}
