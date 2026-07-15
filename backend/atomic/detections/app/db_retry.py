import time

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

# Azure SQL serverless auto-pauses after inactivity. The first query against a
# paused database fails with error 40925 ("database is not currently
# available") while it resumes, which can take up to ~60s. Retry instead of
# surfacing that as a boot crash or a request failure. Budget mirrors the
# azure_db healthcheck gate in docker-compose.yml (12 retries * 10s).
RETRIES = 12
DELAY_SECONDS = 10


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
