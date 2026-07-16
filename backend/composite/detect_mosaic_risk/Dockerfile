FROM python:3.12-slim

WORKDIR /service

COPY composite/detect_mosaic_risk/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/trace_auth trace_auth/
COPY composite/detect_mosaic_risk/app/ app/

ENV FLASK_APP=app.app:create_app
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5008

CMD ["flask", "run"]
