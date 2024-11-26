"""
This is the main Flask app for the PolicyEngine API.
"""

from pathlib import Path
from flask_cors import CORS
import flask
import yaml
from flask_caching import Cache
from policyengine_api.utils import make_cache_key
from .constants import VERSION

# from werkzeug.middleware.profiler import ProfilerMiddleware

# Endpoints
from policyengine_api.routes.error_routes import error_bp
from policyengine_api.routes.economy_routes import economy_bp
from policyengine_api.routes.household_routes import household_bp
from policyengine_api.routes.simulation_analysis_routes import (
    simulation_analysis_bp,
)
from policyengine_api.routes.policy_routes import policy_bp
from policyengine_api.routes.tracer_analysis_routes import tracer_analysis_bp
from policyengine_api.routes.metadata_routes import metadata_bp
from policyengine_api.routes.user_profile_routes import user_profile_bp

from .endpoints import (
    get_home,
    get_policy,
    set_policy,
    get_policy_search,
    get_household_under_policy,
    get_calculate,
    set_user_policy,
    get_user_policy,
    update_user_policy,
    get_simulations,
)

print("Initialising API...")

app = application = flask.Flask(__name__)

app.config.from_mapping(
    {
        "CACHE_TYPE": "RedisCache",
        "CACHE_KEY_PREFIX": "policyengine",
        "CACHE_REDIS_HOST": "127.0.0.1",
        "CACHE_REDIS_PORT": 6379,
        "CACHE_DEFAULT_TIMEOUT": 300,
    }
)
cache = Cache(app)

CORS(app)

app.register_blueprint(error_bp)

app.route("/", methods=["GET"])(get_home)

app.register_blueprint(metadata_bp)

app.register_blueprint(household_bp)

# Routes for getting and setting a "policy" record
app.register_blueprint(policy_bp, url_prefix="/<country_id>/policy")

app.route("/<country_id>/policies", methods=["GET"])(get_policy_search)

app.route(
    "/<country_id>/household/<household_id>/policy/<policy_id>",
    methods=["GET"],
)(get_household_under_policy)

app.route("/<country_id>/calculate", methods=["POST"])(
    cache.cached(make_cache_key=make_cache_key)(get_calculate)
)

app.route("/<country_id>/calculate-full", methods=["POST"])(
    cache.cached(make_cache_key=make_cache_key)(
        lambda *args, **kwargs: get_calculate(
            *args, **kwargs, add_missing=True
        )
    )
)

# Routes for economy microsimulation
app.register_blueprint(economy_bp)

# Routes for AI analysis of economy microsim runs
app.register_blueprint(simulation_analysis_bp)

app.route("/<country_id>/user-policy", methods=["POST"])(set_user_policy)

app.route("/<country_id>/user-policy", methods=["PUT"])(update_user_policy)

app.route("/<country_id>/user-policy/<user_id>", methods=["GET"])(
    get_user_policy
)

app.register_blueprint(user_profile_bp)

app.route("/simulations", methods=["GET"])(get_simulations)

app.register_blueprint(tracer_analysis_bp)


@app.route("/liveness-check", methods=["GET"])
def liveness_check():
    return flask.Response(
        "OK", status=200, headers={"Content-Type": "text/plain"}
    )


@app.route("/readiness-check", methods=["GET"])
def readiness_check():
    return flask.Response(
        "OK", status=200, headers={"Content-Type": "text/plain"}
    )


# Add OpenAPI spec (__file__.parent / openapi_spec.yaml)

with open(Path(__file__).parent / "openapi_spec.yaml", encoding="utf-8") as f:
    openapi_spec = yaml.safe_load(f)
    openapi_spec["info"]["version"] = VERSION


@app.route("/specification", methods=["GET"])
def get_specification():
    return flask.jsonify(openapi_spec)


print("API initialised.")
