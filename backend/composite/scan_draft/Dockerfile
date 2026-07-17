FROM python:3.12-slim

WORKDIR /service

# mediapipe pulls in opencv, whose compiled cv2 bindings need libGL/libglib
# at import time even though pip install succeeds without them — the slim
# base image doesn't ship these by default.
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY composite/scan_draft/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/trace_auth trace_auth/
COPY shared/trace_cors trace_cors/
COPY composite/scan_draft/app/ app/

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-5012} --workers 1 --threads 8 --timeout 0 app.app:'create_app()'"]
