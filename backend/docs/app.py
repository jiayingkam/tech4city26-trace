from flask import Flask
from flask_swagger_ui import get_swaggerui_blueprint

app = Flask(__name__)

swaggerui_bp = get_swaggerui_blueprint(
    "/docs",
    "/docs/swagger",  # placeholder, overridden by urls below
    config={
        "app_name": "Tech4City 2026 - Trace",
        "urls": [
            {"url": "http://localhost:5001/swagger", "name": "Users (atomic)"},
            {"url": "http://localhost:5002/swagger", "name": "Content Drafts (atomic)"},
            {"url": "http://localhost:5003/swagger", "name": "Detections (atomic)"},
            {"url": "http://localhost:5004/swagger", "name": "Edits (atomic)"},
            {"url": "http://localhost:5005/swagger", "name": "Exposure Profiles (atomic)"},
            {"url": "http://localhost:5006/swagger", "name": "Quarantine Items (atomic)"},
            {"url": "http://localhost:5007/swagger", "name": "Compile Family Digest (composite)"},
            {"url": "http://localhost:5008/swagger", "name": "Detect Mosaic Risk (composite)"},
            {"url": "http://localhost:5009/swagger", "name": "Generate Teachable Moment (composite)"},
            {"url": "http://localhost:5010/swagger", "name": "Quarantine High Risk (composite)"},
            {"url": "http://localhost:5011/swagger", "name": "Remediate Content (composite)"},
            {"url": "http://localhost:5012/swagger", "name": "Scan Draft (composite)"},
            {"url": "http://localhost:5013/swagger", "name": "Update Exposure Profile (composite)"},
        ],
    },
)
app.register_blueprint(swaggerui_bp, url_prefix="/docs")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
