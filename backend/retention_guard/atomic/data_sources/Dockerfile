FROM python:3.12-slim

WORKDIR /service

COPY retention_guard/atomic/data_sources/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/trace_auth trace_auth/
COPY shared/trace_cors trace_cors/
# Only data_sources gets trace_crypto copied in — it's the only service that
# ever touches connection-string ciphertext (see plan's Encryption section).
COPY shared/trace_crypto trace_crypto/
COPY retention_guard/atomic/data_sources/app/ app/

# init-db before gunicorn — see business_admins/Dockerfile's comment for why
# this has to live here, not just in docker-compose-retention.yml's local
# command override.
CMD ["sh", "-c", "flask --app app.app:create_app init-db && gunicorn --bind 0.0.0.0:${PORT:-5102} --workers 1 --threads 8 --timeout 0 app.app:'create_app()'"]
