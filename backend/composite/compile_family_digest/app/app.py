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

    # creates a pre-built webpage
    @app.route("/swagger")
    def get_swagger():
        swag = swagger(app)                                  # scans all your route docstrings → builds a dict
        swag["info"]["version"] = "1.0"                     # fills in required fields in that dict
        swag["info"]["title"] = "Compile Family Digest"
        return jsonify(swag)                                 # returns that dict as JSON at /swagger

    swaggerui_bp = get_swaggerui_blueprint(
        "/swagger-ui",
        "/swagger",
        config={"app_name": "Compile Family Digest API"},
    )
    app.register_blueprint(swaggerui_bp, url_prefix="/swagger-ui")

    return app