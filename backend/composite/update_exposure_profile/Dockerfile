FROM python:3.12-slim

WORKDIR /service

COPY composite/update_exposure_profile/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/trace_auth trace_auth/
COPY shared/trace_cors trace_cors/
COPY composite/update_exposure_profile/app/ app/

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-5013} --workers 1 --threads 8 --timeout 0 app.app:'create_app()'"]
