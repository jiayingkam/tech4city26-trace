FROM python:3.12-slim

WORKDIR /service

COPY composite/compile_family_digest/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/trace_auth trace_auth/
COPY composite/compile_family_digest/app/ app/

ENV FLASK_APP=app.app:create_app
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5007

CMD ["flask", "run"]
