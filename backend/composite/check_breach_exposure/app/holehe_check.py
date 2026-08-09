"""Thin wrapper around the self-hosted `holehe` library
(https://github.com/megadose/holehe) — free, open-source, no API key.

Checks whether an email is registered on 120+ platforms by probing each
site's password-reset/signup endpoint. holehe's own CLI drives every module
concurrently via a trio nursery (see holehe/core.py's `import_submodules`/
`get_functions`) rather than one at a time — reused here, so wall-clock time
is bounded by the slowest individual site under HOLEHE_TOTAL_TIMEOUT_S, not
the sum of 120+ sequential requests.
"""
import trio
import httpx

from holehe.core import import_submodules, get_functions

HOLEHE_PER_CALL_TIMEOUT_S = 10
HOLEHE_TOTAL_TIMEOUT_S = 30

# Built once at import time (module discovery + reflection), not per-request.
_functions = get_functions(import_submodules("holehe.modules"))


async def _safe_call(func, email, client, out):
    """Runs a single holehe module, isolating its exceptions.

    trio's structured concurrency means an unhandled exception in ANY task
    started in a nursery cancels every sibling task and aborts the whole
    nursery — not just the task that failed. Most holehe modules catch their
    own request errors and record an {"error": ...} entry in `out` instead of
    raising, but not all of them do (e.g. holehe/modules/shopping/deliveroo.py
    lets a DNS/connection failure propagate). Without this wrapper, one flaky
    site takes down all 120+ others and the whole check reports "unavailable"
    even though every other site would have succeeded. Confirmed live: a
    ConnectError from deliveroo alone was enough to abort the entire run.
    """
    try:
        await func(email, client, out)
    except Exception:
        pass  # this one site's failure just means it's absent from `out`


def check_holehe(email):
    """Check which of 120+ platforms `email` is registered on.

    Returns None if the whole run failed or produced nothing usable at all
    (e.g. the nursery raised) — kept distinct from a real result for the same
    reason as leakcheck.check_leakcheck: a failure must never be displayed as
    "nothing found."

    On success, returns {"total_attempted": int, "conclusive": [...]}.
    `total_attempted` is every module dispatched (~121), not just the ones
    that came back — most sites individually rate-limit a burst of 121
    concurrent requests, so `conclusive` (the subset with a real exists/not
    answer, {"name", "domain", "exists"} each) is routinely well under that.
    Distinguishing the two lets the caller say "checked 121, got a clear
    answer on 42" instead of implying 42 was the whole attempt.
    """
    out = []

    async def _run():
        async with httpx.AsyncClient(timeout=HOLEHE_PER_CALL_TIMEOUT_S) as client:
            with trio.move_on_after(HOLEHE_TOTAL_TIMEOUT_S):
                async with trio.open_nursery() as nursery:
                    for func in _functions:
                        nursery.start_soon(_safe_call, func, email, client, out)

    try:
        trio.run(_run)
    except Exception:
        return None

    if not out:
        return None

    conclusive = [
        {"name": r["name"], "domain": r.get("domain"), "exists": bool(r.get("exists"))}
        for r in out
        if not r.get("error") and not r.get("rateLimit")
    ]
    return {"total_attempted": len(_functions), "conclusive": conclusive}
