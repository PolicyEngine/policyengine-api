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

from .endpoints import (
    get_home,
    get_metadata,
    get_household,
    post_household,
    update_household,
    get_policy,
    set_policy,
    get_policy_search,
    get_household_under_policy,
    get_calculate,
    get_economic_impact,
    execute_simulation_analysis,
    set_user_policy,
    get_user_policy,
    update_user_policy,
    set_user_profile,
    get_user_profile,
    update_user_profile,
    get_simulations,
    execute_tracer_analysis,
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

app.route("/", methods=["GET"])(get_home)

app.route("/<country_id>/metadata", methods=["GET"])(get_metadata)

app.route("/<country_id>/household/<household_id>", methods=["GET"])(
    get_household
)

app.route("/<country_id>/household", methods=["POST"])(post_household)

app.route("/<country_id>/household/<household_id>", methods=["PUT"])(
    update_household
)

app.route("/<country_id>/policy/<policy_id>", methods=["GET"])(get_policy)

app.route("/<country_id>/policy", methods=["POST"])(set_policy)

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

app.route(
    "/<country_id>/economy/<policy_id>/over/<baseline_policy_id>",
    methods=["GET"],
)(get_economic_impact)

app.route("/<country_id>/simulation_analysis", methods=["POST"])(
    execute_simulation_analysis
)

app.route("/<country_id>/user_policy", methods=["POST"])(set_user_policy)

app.route("/<country_id>/user_policy", methods=["PUT"])(update_user_policy)

app.route("/<country_id>/user_policy/<user_id>", methods=["GET"])(
    get_user_policy
)

app.route("/<country_id>/user_profile", methods=["POST"])(set_user_profile)

app.route("/<country_id>/user_profile", methods=["GET"])(get_user_profile)

app.route("/<country_id>/user_profile", methods=["PUT"])(update_user_profile)

app.route("/simulations", methods=["GET"])(get_simulations)

app.route("/simulations", methods=["GET"])(get_simulations)

app.route("/<country_id>/tracer_analysis", methods=["POST"])(
    execute_tracer_analysis
)


@app.route("/liveness_check", methods=["GET"])
def liveness_check():
    return flask.Response(
        "OK", status=200, headers={"Content-Type": "text/plain"}
    )


@app.route("/readiness_check", methods=["GET"])
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
