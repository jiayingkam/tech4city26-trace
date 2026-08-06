from flask import Flask
from flask_swagger_ui import get_swaggerui_blueprint

app = Flask(__name__)

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
            {"url": "http://localhost:5101/swagger", "name": "Business Admins (atomic)"},
            {"url": "http://localhost:5102/swagger", "name": "Data Sources (atomic)"},
            {"url": "http://localhost:5103/swagger", "name": "Retention Policies (atomic)"},
            {"url": "http://localhost:5104/swagger", "name": "Audit Log (atomic)"},
            {"url": "http://localhost:5105/swagger", "name": "Enforce Retention (composite)"},
        ],
    },
)
app.register_blueprint(swaggerui_bp, url_prefix="/docs")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5100)
