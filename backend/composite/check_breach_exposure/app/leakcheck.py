"""Thin client for LeakCheck's Public API (https://leakcheck.io/api/public).

Free, unauthenticated, rate-limited to 1 request/second. Returns only breach
*source names* and the *categories* of exposed data — never the leaked data
itself (that's the paid Pro API, which this app deliberately does not use).

Isolated in its own module, same separation `detect_mosaic_risk` gives its
OpenAI call in `extraction.py` — keeps the external-call/failure-handling
concerns out of routes.py.
"""
import threading
import time

import requests

LEAKCHECK_URL = "https://leakcheck.io/api/public"

# LeakCheck's cap is 1 req/sec for the whole app, not per-user — a per-user
# lock wouldn't help when multiple users check concurrently. A single
# process-wide lock + last-call timestamp serializes every caller through
# the window. Correct for this deployment (--workers 1, gunicorn threads
# only); would need a shared/external limiter if this ever ran multi-worker
# or multi-instance, which is out of scope for a hackathon demo.
_MIN_INTERVAL_S = 1.05  # small margin over 1.0s against clock jitter
_rate_lock = threading.Lock()
_last_call_ts = 0.0


def check_leakcheck(email):
    """Check whether `email` appears in LeakCheck's breach database.

    Returns a dict {"found": bool, "fields": [...], "sources": [...]} on a
    successful call — including a successful call that found nothing
    (`found: False`). Returns None if the call itself failed (network error,
    rate-limited, non-200, malformed body) — this is deliberately distinct
    from a real "not found" result, same None-vs-empty convention used by
    detect_mosaic_risk/extraction.py, so a transient failure can never be
    displayed to a user as "you're clear."
    """
    global _last_call_ts

    with _rate_lock:
        wait = _MIN_INTERVAL_S - (time.monotonic() - _last_call_ts)
        if wait > 0:
            time.sleep(wait)
        try:
            resp = requests.get(LEAKCHECK_URL, params={"check": email}, timeout=8)
        except requests.RequestException:
            _last_call_ts = time.monotonic()
            return None
        _last_call_ts = time.monotonic()

    if resp.status_code != 200:
        return None
    try:
        body = resp.json()
    except ValueError:
        return None

    if not body.get("success"):
        # Confirmed live against the real API: a clean (no-breach) result
        # comes back as {"success": false, "error": "Not found"} — NOT as
        # {"success": true, "found": 0, ...} the way the (incomplete) docs
        # imply. Every other success:false case seen (e.g. "Enter at least 3
        # characters to search") is a genuine input/validation error, so only
        # this one specific message means "checked, nothing found."
        if str(body.get("error", "")).strip().lower() == "not found":
            return {"found": False, "fields": [], "sources": []}
        return None

    return {
        "found": bool(body.get("found")),
        "fields": body.get("fields") or [],
        "sources": body.get("sources") or [],
    }
