from os import environ
from flask import Flask, jsonify
from flask_cors import CORS
from flask_swagger import swagger
from flask_swagger_ui import get_swaggerui_blueprint
from dotenv import load_dotenv
from .db import db

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

    from .routes import bp
    app.register_blueprint(bp)

    with app.app_context():
        db.create_all()

    # creates a pre-built webpage
    @app.route("/swagger")
    def get_swagger():
        swag = swagger(app)                   # scans all your route docstrings → builds a dict
        swag["info"]["version"] = "1.0"       # fills in required fields in that dict
        swag["info"]["title"] = "Content Drafts API"
        return jsonify(swag)                  # returns that dict as JSON at /swagger

    swaggerui_bp = get_swaggerui_blueprint(
        "/swagger-ui",
        "/swagger",
        config={"app_name": "Content Drafts API"},
    )
    app.register_blueprint(swaggerui_bp, url_prefix="/swagger-ui")

    return app