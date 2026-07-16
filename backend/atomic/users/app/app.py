from os import environ
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_swagger import swagger
from flask_swagger_ui import get_swaggerui_blueprint
from dotenv import load_dotenv
from .db import db
from .db_retry import wait_for_db
from trace_auth import init_auth

load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app, origins=environ.get("FRONTEND_ORIGIN", "http://localhost:3000").split(","))

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
    init_auth(app, public_paths={"/signup", "/login"})

    from .routes import users_bp
    app.register_blueprint(users_bp)

    with app.app_context():
        wait_for_db(db.engine)
        db.create_all()

    @app.before_request
    def _wait_for_db_before_request():
        # Let health/swagger checks respond immediately even if the DB is
        # still resuming, so Render doesn't treat a resuming DB as a dead
        # service and restart it.
        if request.path == "/health" or request.path.startswith("/swagger"):
            return
        wait_for_db(db.engine)

    @app.route("/swagger")
    def get_swagger():
        swag = swagger(app)
        swag["info"]["version"] = "1.0"
        swag["info"]["title"] = "Users API"
        return jsonify(swag)

    swaggerui_bp = get_swaggerui_blueprint(
        "/swagger-ui",
        "/swagger",
        config={"app_name": "Users API"},
    )
    app.register_blueprint(swaggerui_bp, url_prefix="/swagger-ui")

    return app
