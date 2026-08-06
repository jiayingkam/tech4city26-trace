FROM python:3.12-slim

WORKDIR /service

# Unlike TRACE's own atomic services, retention_guard's metadata DB is
# Postgres (see plan §Decisions Locked In) — psycopg2-binary needs no
# msodbcsql18/unixodbc-dev apt install, so this image builds faster and
# smaller than atomic/users' Dockerfile.
COPY retention_guard/atomic/business_admins/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/trace_auth trace_auth/
COPY shared/trace_cors trace_cors/
COPY retention_guard/atomic/business_admins/app/ app/

# init-db before gunicorn — db.create_all() is idempotent against Postgres,
# so this is safe on every boot (matches docker-compose-retention.yml's
# local command override). Without this, Cloud Run's deploy path never ran
# init-db at all (no separate manual step exists for it here, unlike
# TRACE's Azure-backed atomic services), so a fresh production DB was left
# with no tables — every route touching the DB 500'd until this was added.
CMD ["sh", "-c", "flask --app app.app:create_app init-db && gunicorn --bind 0.0.0.0:${PORT:-5101} --workers 1 --threads 8 --timeout 0 app.app:'create_app()'"]
