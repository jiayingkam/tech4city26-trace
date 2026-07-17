import re
from os import environ
from flask_cors import CORS

# A real caller's browser can never present an Origin of http://localhost:<port>
# to a deployed service — that header reflects the page's actual origin, not
# something a remote client can spoof — so allowing any localhost port is safe
# in every environment, not just dev. That means a frontend dev server that
# lands on a different port (Vite's strictPort: false, a stale process on the
# usual port, etc.) doesn't require FRONTEND_ORIGIN to be updated and
# redeployed just to keep working.
LOCALHOST_ORIGIN = re.compile(r"^http://localhost:\d+$")


def configure_cors(app):
    """Single source of truth for every service's CORS origin whitelist.
    Copied into each service's container at build time (see each Dockerfile's
    `COPY shared/trace_cors trace_cors/`), same as trace_auth."""
    configured = environ.get("FRONTEND_ORIGIN", "http://localhost:3000").split(",")
    CORS(app, origins=[*configured, LOCALHOST_ORIGIN])
