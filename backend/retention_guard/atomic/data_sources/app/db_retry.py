import time

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

# Same retry rationale as business_admins/app/db_retry.py — gated behind
# retention_guard_db's own healthcheck, this just covers the moment right
# after that where the DB may not yet accept new connections.
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
