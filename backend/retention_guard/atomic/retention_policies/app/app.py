from os import environ
from flask import Flask, jsonify, request
from flask_swagger import swagger
from flask_swagger_ui import get_swaggerui_blueprint
from dotenv import load_dotenv
from sqlalchemy.engine import URL
from werkzeug.exceptions import HTTPException
from .db import db
from .db_retry import wait_for_db
from trace_auth import init_auth
from trace_cors import configure_cors

load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__)
    configure_cors(app)

    app.config["SQLALCHEMY_DATABASE_URI"] = URL.create(
        "postgresql+psycopg2",
        username=environ["DB_USER"],
        password=environ["DB_PASSWORD"],
        host=environ["DB_SERVER"],
        port=int(environ.get("DB_PORT", 5432)),
        database=environ["DB_NAME"],
    ).render_as_string(hide_password=False)
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }
    db.init_app(app)
    init_auth(app)

    from .routes import retention_policies_bp
    app.register_blueprint(retention_policies_bp)

    @app.before_request
    def _wait_for_db_before_request():
        if request.method == "OPTIONS" or request.path == "/health" or request.path.startswith("/swagger"):
            return
        wait_for_db(db.engine)

    @app.cli.command("init-db")
    def init_db():
        wait_for_db(db.engine)
        db.create_all()

    @app.errorhandler(Exception)
    def _json_unhandled_error(error):
        if isinstance(error, HTTPException):
            return error
        app.logger.exception("Unhandled retention_policies service error", exc_info=error)
        return jsonify({"error": "internal server error"}), 500

    @app.route("/swagger")
    def get_swagger():
        swag = swagger(app)
        swag["info"]["version"] = "1.0"
        swag["info"]["title"] = "Retention Policies API"
        swag["securityDefinitions"] = {
            "BearerAuth": {"type": "apiKey", "name": "Authorization", "in": "header"},
            "InternalApiKey": {"type": "apiKey", "name": "X-Internal-Key", "in": "header"},
        }
        return jsonify(swag)

    swaggerui_bp = get_swaggerui_blueprint(
        "/swagger-ui",
        "/swagger",
        config={"app_name": "Retention Policies API"},
    )
    app.register_blueprint(swaggerui_bp, url_prefix="/swagger-ui")

    return app
