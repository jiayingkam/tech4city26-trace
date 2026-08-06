FROM python:3.12-slim

WORKDIR /service

COPY retention_guard/composite/enforce_retention/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/trace_auth trace_auth/
COPY shared/trace_cors trace_cors/
COPY retention_guard/composite/enforce_retention/app/ app/

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-5105} --workers 1 --threads 8 --timeout 0 app.app:'create_app()'"]
