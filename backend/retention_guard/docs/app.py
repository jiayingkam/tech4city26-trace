from flask import Flask, jsonify
from flask_swagger_ui import get_swaggerui_blueprint

app = Flask(__name__)


@app.get("/health")
def health():
    # This page has no DB/dependencies to actually check readiness against —
    # this route exists purely so a Cloud Run health check (which every
    # other retention_guard service has one of, at this same path) has
    # something to hit instead of 404ing and marking the instance unhealthy.
    return jsonify({"status": "ok"}), 200

# Deliberately its own aggregator, separate from backend/docs/app.py — this
# lets someone browse/try the whole retention_guard product without TRACE's
# other ~17 services running (see plan §Docker/local dev/deploy). Same
# hardcoded-urls pattern as the main docs app: flask-swagger-ui doesn't
# auto-discover services, each new one needs a line added here by hand.
swaggerui_bp = get_swaggerui_blueprint(
    "/docs",
    "/docs/swagger",  # placeholder, overridden by urls below
    config={
        "app_name": "Retention Guard - PDPA Data Retention API",
        "urls": [
            {"url": "https://retention-business-admins-658022855661.asia-southeast1.run.app/swagger", "name": "Business Admins (atomic)"},
            {"url": "https://retention-data-sources-658022855661.asia-southeast1.run.app/swagger", "name": "Data Sources (atomic)"},
            {"url": "https://retention-retention-policies-658022855661.asia-southeast1.run.app/swagger", "name": "Retention Policies (atomic)"},
            {"url": "https://retention-audit-log-658022855661.asia-southeast1.run.app/swagger", "name": "Audit Log (atomic)"},
            {"url": "https://retention-enforce-retention-658022855661.asia-southeast1.run.app/swagger", "name": "Enforce Retention (composite)"},
        ],
    },
)
app.register_blueprint(swaggerui_bp, url_prefix="/docs")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5100)
