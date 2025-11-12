"""
This is the main Flask app for the PolicyEngine API.
"""

import time
import sys
import os

start_time = time.time()


def log_timing(message):
    elapsed = time.time() - start_time
    print(f"[{elapsed:.2f}s] {message}", file=sys.stderr, flush=True)


from pathlib import Path
from .constants import VERSION

log_timing("Basic imports completed")

from flask_cors import CORS
import flask

log_timing("Flask imports completed")

from flask_caching import Cache
from policyengine_api.utils import make_cache_key

log_timing("Caching utilities import completed")

import yaml

log_timing("YAML import completed")

# from werkzeug.middleware.profiler import ProfilerMiddleware

# Endpoints
from policyengine_api.routes.error_routes import error_bp

log_timing("Error routes import completed")
from policyengine_api.routes.economy_routes import economy_bp

log_timing("Economy routes import completed")
from policyengine_api.routes.household_routes import household_bp

log_timing("Household routes import completed")
from policyengine_api.routes.simulation_analysis_routes import (
    simulation_analysis_bp,
)

log_timing("Simulation analysis routes import completed")
from policyengine_api.routes.policy_routes import policy_bp

log_timing("Policy routes import completed")
from policyengine_api.routes.tracer_analysis_routes import tracer_analysis_bp

log_timing("Tracer analysis routes import completed")
from policyengine_api.routes.metadata_routes import metadata_bp

log_timing("Metadata routes import completed")
from policyengine_api.routes.user_profile_routes import user_profile_bp

log_timing("User profile routes import completed")
from policyengine_api.routes.ai_prompt_routes import ai_prompt_bp
from policyengine_api.routes.simulation_routes import simulation_bp
from policyengine_api.routes.report_output_routes import report_output_bp

log_timing("Base AI routes import completed")

from .endpoints import (
    get_home,
    get_policy_search,
    get_household_under_policy,
    get_calculate,
    set_user_policy,
    get_user_policy,
    update_user_policy,
    get_simulations,
)

log_timing("Legacy endpoints import completed")

log_timing("Initialising API...")

app = application = flask.Flask(__name__)
log_timing("Flask app created")

app.config.from_mapping(
    {
        "CACHE_TYPE": "RedisCache",
        "CACHE_KEY_PREFIX": "policyengine",
        "CACHE_REDIS_HOST": os.getenv("CACHE_REDIS_HOST", "127.0.0.1"),
        "CACHE_REDIS_PORT": 6379,
        "CACHE_DEFAULT_TIMEOUT": 300,
    }
)
cache = Cache(app)
log_timing("Caching initialised")

CORS(app)
log_timing("CORS initialised")

app.register_blueprint(error_bp)
log_timing("Error routes registered")

app.route("/", methods=["GET"])(get_home)
log_timing("Home routes registered")

app.register_blueprint(metadata_bp)
log_timing("Metadata routes registered")

app.register_blueprint(household_bp)
log_timing("Household routes registered")

# Routes for getting and setting a "policy" record
app.register_blueprint(policy_bp)
log_timing("Policy routes registered")

app.route("/<country_id>/policies", methods=["GET"])(get_policy_search)
log_timing("Policy search endpoint registered")

app.route(
    "/<country_id>/household/<household_id>/policy/<policy_id>",
    methods=["GET"],
)(get_household_under_policy)
log_timing("Household under policy endpoint registered")

app.route("/<country_id>/calculate", methods=["POST"])(
    cache.cached(make_cache_key=make_cache_key)(get_calculate)
)
log_timing("Calculate endpoint registered")

app.route("/<country_id>/calculate-full", methods=["POST"])(
    cache.cached(make_cache_key=make_cache_key)(
        lambda *args, **kwargs: get_calculate(
            *args, **kwargs, add_missing=True
        )
    )
)
log_timing("Calculate-full endpoint registered")

# Routes for economy microsimulation
app.register_blueprint(economy_bp)
log_timing("Economy routes registered")

# Routes for AI analysis of economy microsim runs
app.register_blueprint(simulation_analysis_bp)
log_timing("Simulation analysis routes registered")

app.route("/<country_id>/user-policy", methods=["POST"])(set_user_policy)
log_timing("User policy set endpoint registered")

app.route("/<country_id>/user-policy", methods=["PUT"])(update_user_policy)
log_timing("User policy update endpoint registered")

app.route("/<country_id>/user-policy/<user_id>", methods=["GET"])(
    get_user_policy
)
log_timing("User policy get endpoint registered")

app.register_blueprint(user_profile_bp)
log_timing("User profile routes registered")

app.route("/simulations", methods=["GET"])(get_simulations)
log_timing("Simulations endpoint registered")

app.register_blueprint(tracer_analysis_bp)
log_timing("Tracer analysis routes registered")

app.register_blueprint(ai_prompt_bp)
log_timing("AI prompt routes registered")

app.register_blueprint(simulation_bp)

app.register_blueprint(report_output_bp)


@app.route("/liveness-check", methods=["GET"])
def liveness_check():
    return flask.Response(
        "OK", status=200, headers={"Content-Type": "text/plain"}
    )


log_timing("Liveness check endpoint registered")


@app.route("/readiness-check", methods=["GET"])
def readiness_check():
    return flask.Response(
        "OK", status=200, headers={"Content-Type": "text/plain"}
    )


log_timing("Readiness check endpoint registered")


# Add OpenAPI spec (__file__.parent / openapi_spec.yaml)

with open(Path(__file__).parent / "openapi_spec.yaml", encoding="utf-8") as f:
    openapi_spec = yaml.safe_load(f)
    openapi_spec["info"]["version"] = VERSION
log_timing("OpenAPI spec loaded")


@app.route("/specification", methods=["GET"])
def get_specification():
    return flask.jsonify(openapi_spec)


log_timing("Specification endpoint registered")


log_timing("API initialised.")
