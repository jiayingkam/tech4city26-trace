from flask import Flask, jsonify
from flask_swagger import swagger
from flask_swagger_ui import get_swaggerui_blueprint
from dotenv import load_dotenv
from trace_auth import init_auth
from trace_cors import configure_cors

load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__)
    configure_cors(app)
    init_auth(app)

    from .routes import bp
    app.register_blueprint(bp)

    @app.route("/swagger")
    def get_swagger():
        swag = swagger(app)
        swag["info"]["version"] = "1.0"
        swag["info"]["title"] = "Manage History"
        # Lets Swagger UI's "Authorize" button attach the bearer token or
        # internal key that routes declare via `security:` in their docstrings.
        swag["securityDefinitions"] = {
            "BearerAuth": {"type": "apiKey", "name": "Authorization", "in": "header"},
            "InternalApiKey": {"type": "apiKey", "name": "X-Internal-Key", "in": "header"},
        }
        return jsonify(swag)

    swaggerui_bp = get_swaggerui_blueprint(
        "/swagger-ui",
        "/swagger",
        config={"app_name": "Manage History"},
    )
    app.register_blueprint(swaggerui_bp, url_prefix="/swagger-ui")

    return app
