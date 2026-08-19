# ruff: noqa: E402
"""
This is the main Flask app for the PolicyEngine API.
"""

import time
import sys

start_time = time.time()


def log_timing(message):
    elapsed = time.time() - start_time
    print(f"[{elapsed:.2f}s] {message}", file=sys.stderr, flush=True)


log_timing("Basic imports completed")

from flask_cors import CORS
import flask

log_timing("Flask imports completed")

from policyengine_api.extensions import cache
from policyengine_api.migration_logging import register_migration_request_logging
from policyengine_api.runtime_cache.settings import load_runtime_cache_settings

log_timing("Caching utilities import completed")

# from werkzeug.middleware.profiler import ProfilerMiddleware

# Endpoints
from policyengine_api.routes.error_routes import error_bp

log_timing("Error routes import completed")
from policyengine_api.routes.home_routes import home_bp

log_timing("Home routes import completed")
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
from policyengine_api.routes.reform_impact_routes import reform_impact_bp
from policyengine_api.routes.system_routes import system_bp

log_timing("Base AI routes import completed")

log_timing("Initialising API...")

app = application = flask.Flask(__name__)
log_timing("Flask app created")

runtime_cache_settings = load_runtime_cache_settings()
if runtime_cache_settings.enabled:
    app.config.from_mapping(
        {
            "CACHE_TYPE": "RedisCache",
            "CACHE_KEY_PREFIX": (
                "policyengine:"
                f"{runtime_cache_settings.environment}:"
                f"{runtime_cache_settings.service}:flask:v1:"
            ),
            "CACHE_REDIS_URL": (
                runtime_cache_settings.url.get_secret_value()
                if runtime_cache_settings.url is not None
                else None
            ),
            "CACHE_DEFAULT_TIMEOUT": 300,
            "CACHE_OPTIONS": (
                {
                    "ssl_cert_reqs": "required",
                    "ssl_ca_data": runtime_cache_settings.ca_cert.get_secret_value(),
                }
                if runtime_cache_settings.tls
                and runtime_cache_settings.ca_cert is not None
                else {}
            ),
        }
    )
else:
    app.config.from_mapping(
        {
            "CACHE_TYPE": "NullCache",
            "CACHE_KEY_PREFIX": "policyengine:test:api:flask:v1:",
            "CACHE_DEFAULT_TIMEOUT": 300,
        }
    )
cache.init_app(app)
log_timing("Caching initialised")

CORS(app)
log_timing("CORS initialised")

register_migration_request_logging(app)
log_timing("Migration request logging initialised")

app.register_blueprint(error_bp)
log_timing("Error routes registered")

app.register_blueprint(home_bp)
log_timing("Home routes registered")

app.register_blueprint(metadata_bp)
log_timing("Metadata routes registered")

app.register_blueprint(household_bp)
log_timing("Household routes registered")

# Routes for getting and setting a "policy" record
app.register_blueprint(policy_bp)
log_timing("Policy routes registered")

# Routes for economy microsimulation
app.register_blueprint(economy_bp)
log_timing("Economy routes registered")

# Routes for AI analysis of economy microsim runs
app.register_blueprint(simulation_analysis_bp)
log_timing("Simulation analysis routes registered")

app.register_blueprint(user_profile_bp)
log_timing("User profile routes registered")

app.register_blueprint(reform_impact_bp)
log_timing("Simulations endpoint registered")

app.register_blueprint(tracer_analysis_bp)
log_timing("Tracer analysis routes registered")

app.register_blueprint(ai_prompt_bp)
log_timing("AI prompt routes registered")

app.register_blueprint(simulation_bp)

app.register_blueprint(report_output_bp)
app.register_blueprint(system_bp)
log_timing("System routes registered")


log_timing("API initialised.")
