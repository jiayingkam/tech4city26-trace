from os import environ
from flask import Flask, jsonify, request
from flask_swagger import swagger
from flask_swagger_ui import get_swaggerui_blueprint
from dotenv import load_dotenv
from .db import db
from .db_retry import wait_for_db
from trace_auth import init_auth
from trace_cors import configure_cors

load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__)
    configure_cors(app)

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
    init_auth(app)

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

    # creates a pre-built webpage
    @app.route("/swagger")
    def get_swagger():
        swag = swagger(app)                   # scans all your route docstrings → builds a dict
        swag["info"]["version"] = "1.0"       # fills in required fields in that dict
        swag["info"]["title"] = "Content Drafts API"
        # Lets Swagger UI's "Authorize" button attach the bearer token that
        # routes declare via `security: - BearerAuth: []` in their docstrings.
        swag["securityDefinitions"] = {
            "BearerAuth": {"type": "apiKey", "name": "Authorization", "in": "header"}
        }
        return jsonify(swag)                  # returns that dict as JSON at /swagger

    swaggerui_bp = get_swaggerui_blueprint(
        "/swagger-ui",
        "/swagger",
        config={"app_name": "Content Drafts API"},
    )
    app.register_blueprint(swaggerui_bp, url_prefix="/swagger-ui")

    return app