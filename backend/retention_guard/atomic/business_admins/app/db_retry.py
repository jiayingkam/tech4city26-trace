import time

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

# Compose's `depends_on: condition: service_healthy` already gates every
# retention_guard service behind retention_guard_db's own pg_isready
# healthcheck, but the DB can still take a moment after that to accept new
# connections (and a hosted Postgres used outside local dev can have brief
# connection hiccups of its own) — retry instead of surfacing that as a boot
# crash or a request failure.
RETRIES = 12
DELAY_SECONDS = 5


def wait_for_db(engine):
    for attempt in range(1, RETRIES + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except OperationalError:
            if attempt == RETRIES:
                raise
            time.sleep(DELAY_SECONDS)
