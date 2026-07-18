import re
from os import environ
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_swagger import swagger
from flask_swagger_ui import get_swaggerui_blueprint
from dotenv import load_dotenv
from .db import db
from .db_retry import wait_for_db

load_dotenv()

# This service's Docker build context (./atomic/exposure_profiles, see
# docker-compose.yml) doesn't reach backend/shared, so it can't import the
# trace_cors helper the other services use — duplicated here instead. Any
# localhost port is allowed alongside FRONTEND_ORIGIN because that header is
# browser-set and can't be spoofed by a real remote caller, so it's safe in
# every environment.
LOCALHOST_ORIGIN = re.compile(r"^http://localhost:\d+$")


def create_app() -> Flask:
    app = Flask(__name__)
    configured_origins = environ.get("FRONTEND_ORIGIN", "http://localhost:3000").split(",")
    CORS(app, origins=[*configured_origins, LOCALHOST_ORIGIN])

    db_server = environ["DB_SERVER"]
    db_name = environ["DB_NAME"]
    db_user = environ["DB_USER"]
    db_password = environ["DB_PASSWORD"]
    driver = "ODBC+Driver+18+for+SQL+Server"
    app.config["SQLALCHEMY_DATABASE_URI"] = (
        f"mssql+pyodbc://{db_user}:{db_password}@{db_server}/{db_name}"
        f"?driver={driver}&Encrypt=yes&TrustServerCertificate=no&Connection+Timeout=30"
    )
    # Azure SQL silently drops idle connections; without pre_ping, the next
    # query on a stale pooled connection dies with a raw TCP/communication
    # link error instead of transparently reconnecting.
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }
    db.init_app(app)

    from .routes import bp
    app.register_blueprint(bp)

    @app.before_request
    def _wait_for_db_before_request():
        # Let health/swagger checks respond immediately even if the DB is
        # still resuming, so Cloud Run doesn't treat a resuming DB as a dead
        # service and restart it. CORS preflight (OPTIONS) never touches the
        # database either — no reason to make the browser wait on it before
        # it's even sent the real request.
        if request.method == "OPTIONS" or request.path == "/health" or request.path.startswith("/swagger"):
            return
        wait_for_db(db.engine)

    @app.cli.command("init-db")
    def init_db():
        # Schema setup used to run on every cold start via app.app_context()
        # here, which meant every boot paid for both a DB wake-up wait and a
        # full schema re-check. It only needs to happen once ever, so it's a
        # manual command now: `flask --app app.app:create_app init-db`.
        wait_for_db(db.engine)
        db.create_all()

    @app.route("/swagger")
    def get_swagger():
        swag = swagger(app)
        swag["info"]["version"] = "1.0"
        swag["info"]["title"] = "Exposure Profiles API"
        return jsonify(swag)

    swaggerui_bp = get_swaggerui_blueprint(
        "/swagger-ui",
        "/swagger",
        config={"app_name": "Exposure Profiles API"},
    )
    app.register_blueprint(swaggerui_bp, url_prefix="/swagger-ui")

    return app
