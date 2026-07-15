FROM python:3.12-slim

WORKDIR /service

# mediapipe pulls in opencv, whose compiled cv2 bindings need libGL/libglib
# at import time even though pip install succeeds without them — the slim
# base image doesn't ship these by default.
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/

ENV FLASK_APP=app.app:create_app
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5012

CMD ["flask", "run"]
