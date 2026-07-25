FROM python:3.12-slim

WORKDIR /service

# Deliberately no libgl1/libglib2.0-0/mediapipe/opencv here (unlike
# scan_draft) — video findings come from Cloud Video Intelligence itself
# (face tracks, on-screen text), never a local decode/pose pipeline, so this
# container stays light. That's the whole reason this is its own service
# instead of another scanner bolted onto scan_draft: scan_draft's mediapipe
# stack is already the heaviest thing in the fleet memory-wise.
COPY composite/scan_video/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/trace_auth trace_auth/
COPY shared/trace_cors trace_cors/
COPY shared/trace_storage trace_storage/
COPY composite/scan_video/app/ app/

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-5016} --workers 1 --threads 8 --timeout 0 app.app:'create_app()'"]
