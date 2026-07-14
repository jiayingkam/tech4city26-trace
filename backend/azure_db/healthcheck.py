import sys
from os import environ

import certifi
import pytds

try:
    with pytds.connect(
        server=environ["DB_SERVER"],
        database=environ["DB_NAME"],
        user=environ["DB_USER"],
        password=environ["DB_PASSWORD"],
        cafile=certifi.where(),
        timeout=5,
        login_timeout=5,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
except Exception as exc:
    reason = exc.__cause__ or exc
    print(f"azure_db healthcheck failed: {reason!r}", file=sys.stderr)
    sys.exit(1)
