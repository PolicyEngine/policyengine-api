"""
This is the main Flask app for the PolicyEngine API.
"""

print(f"Initialising API...")

import flask
from flask_cors import CORS
from pathlib import Path
import yaml
from .constants import VERSION

# Endpoints

from .endpoints import (
    get_home,
    get_metadata,
    get_household,
    post_household,
    get_policy,
    set_policy,
    get_policy_search,
    get_household_under_policy,
    get_calculate,
    get_economic_impact,
    get_analysis,
    get_search,
)

app = application = flask.Flask(__name__)

CORS(app)

app.route("/", methods=["GET"])(get_home)

app.route("/<country_id>/metadata", methods=["GET"])(get_metadata)

app.route("/<country_id>/household/<household_id>", methods=["GET"])(
    get_household
)

app.route("/<country_id>/household", methods=["POST"])(post_household)

app.route("/<country_id>/policy/<policy_id>", methods=["GET"])(get_policy)

app.route("/<country_id>/policy", methods=["POST"])(set_policy)

app.route("/<country_id>/policies", methods=["GET"])(get_policy_search)

app.route(
    "/<country_id>/household/<household_id>/policy/<policy_id>",
    methods=["GET"],
)(get_household_under_policy)

app.route("/<country_id>/calculate", methods=["POST"])(get_calculate)

app.route(
    "/<country_id>/economy/<policy_id>/over/<baseline_policy_id>",
    methods=["GET"],
)(get_economic_impact)

app.route("/<country_id>/analysis", methods=["POST"])(
    app.route("/<country_id>/analysis/<prompt_id>", methods=["GET"])(
        get_analysis
    )
)

app.route("/<country_id>/search", methods=["GET"])(get_search)


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

with open(Path(__file__).parent / "openapi_spec.yaml") as f:
    openapi_spec = yaml.safe_load(f)
    openapi_spec["info"]["version"] = VERSION


@app.route("/specification", methods=["GET"])
def get_specification():
    return flask.jsonify(openapi_spec)


print(f"API initialised.")
