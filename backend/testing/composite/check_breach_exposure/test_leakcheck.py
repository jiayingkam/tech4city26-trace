"""Unit tests for leakcheck.py's response parsing specifically — the
routes.py test suite only ever mocks check_leakcheck itself, so it can't
catch a bug in how this module interprets LeakCheck's actual response shape.
These responses (particularly the "not found" case) were confirmed against
the real live API, not assumed from LeakCheck's own (incomplete) docs.
"""
from unittest.mock import MagicMock, patch

from backend.composite.check_breach_exposure.app.leakcheck import check_leakcheck


def _resp(status_code, json_body=None, raise_on_json=False):
    response = MagicMock()
    response.status_code = status_code
    if raise_on_json:
        response.json.side_effect = ValueError("not json")
    else:
        response.json.return_value = json_body
    return response


def test_found_result_is_reported_as_found():
    body = {
        "success": True,
        "found": 3,
        "fields": ["username", "password"],
        "sources": [{"name": "Evony.com", "date": "2016-07"}],
    }
    with patch("backend.composite.check_breach_exposure.app.leakcheck.requests") as mocked_requests:
        mocked_requests.get.return_value = _resp(200, body)
        result = check_leakcheck("breached@example.com")

    assert result == {"found": True, "fields": ["username", "password"], "sources": [{"name": "Evony.com", "date": "2016-07"}]}


def test_genuinely_clean_result_is_reported_as_not_found_not_unavailable():
    """Regression test: LeakCheck's real API reports "nothing found" as
    {"success": false, "error": "Not found"} — NOT {"success": true, "found":
    0}. Treating every success:false as a failure (the original bug) meant
    every clean email was wrongly reported as "couldn't check" instead of
    "not found." Confirmed against the real API, not just the docs."""
    with patch("backend.composite.check_breach_exposure.app.leakcheck.requests") as mocked_requests:
        mocked_requests.get.return_value = _resp(200, {"success": False, "error": "Not found"})
        result = check_leakcheck("clean@example.com")

    assert result == {"found": False, "fields": [], "sources": []}


def test_a_real_api_error_still_returns_none():
    with patch("backend.composite.check_breach_exposure.app.leakcheck.requests") as mocked_requests:
        mocked_requests.get.return_value = _resp(200, {"success": False, "error": "Enter at least 3 characters to search"})
        result = check_leakcheck("ab")

    assert result is None


def test_non_200_status_returns_none():
    with patch("backend.composite.check_breach_exposure.app.leakcheck.requests") as mocked_requests:
        mocked_requests.get.return_value = _resp(429)
        result = check_leakcheck("someone@example.com")

    assert result is None


def test_malformed_json_returns_none():
    with patch("backend.composite.check_breach_exposure.app.leakcheck.requests") as mocked_requests:
        mocked_requests.get.return_value = _resp(200, raise_on_json=True)
        result = check_leakcheck("someone@example.com")

    assert result is None


def test_network_error_returns_none():
    import requests

    with patch("backend.composite.check_breach_exposure.app.leakcheck.requests") as mocked_requests:
        mocked_requests.get.side_effect = requests.ConnectionError("boom")
        mocked_requests.RequestException = requests.RequestException
        result = check_leakcheck("someone@example.com")

    assert result is None
