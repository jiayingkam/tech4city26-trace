FROM python:3.12-slim

WORKDIR /service

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# gunicorn + a dynamic $PORT bind, matching every other retention_guard
# service's Dockerfile — Cloud Run injects its own PORT (usually 8080) and
# expects the container to listen there; the previous "flask run" +
# hardcoded FLASK_RUN_PORT=5100 ignored that entirely and would have failed
# to come up on Cloud Run.
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-5100} --workers 1 --threads 8 --timeout 0 app:app"]
