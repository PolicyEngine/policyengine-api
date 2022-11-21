import flask
import requests
from flask_cors import CORS
import json
from policyengine_api.constants import GET, POST, LIST, UPDATE, REPO, VERSION
from policyengine_api.country import PolicyEngineCountry
from policyengine_api.utils import hash_object, safe_endpoint
from policyengine_api.data import PolicyEngineDatabase
from policyengine_api.endpoints import metadata, get_household, set_household, get_policy, set_policy, get_household_under_policy, search_policies, get_current_law_policy_id

app = flask.Flask(__name__)

CORS(app)

uk = PolicyEngineCountry("policyengine_uk")
us = PolicyEngineCountry("policyengine_us")
countries = dict(uk=uk, us=us)

database = PolicyEngineDatabase(local=True, initialize=True)

API = "http://localhost:5000"
COMPUTE_API = "http://localhost:5001"


@app.route("/", methods=[GET])
def home():
    return f"<h1>PolicyEngine households API v{VERSION}</h1><p>Use this API to compute the impact of public policy on individual households.</p>"


app.route("/<country_id>/metadata", methods=[GET])
@safe_endpoint
def get_metadata(country_id: str):
    return metadata(country_id)

@app.route("/<country_id>/household/<household_id>", methods=[GET, POST])
@safe_endpoint
def household(country_id: str, household_id: str):
    if flask.request.method == GET:
        return get_household(country_id, household_id=household_id)
    elif flask.request.method == POST:
        payload = flask.request.json
        label = payload.get("label")
        household_json = payload.get("data")
        return set_household(country_id, household_id, household_json, label=label)

@app.route("/<country_id>/household", methods=[POST])
@safe_endpoint
def new_household(country_id: str):
    payload = flask.request.json
    label = payload.get("label")
    household_json = payload.get("data")
    return set_household(country_id, None, household_json, label=label)

@app.route("/<country_id>/policy/<policy_id>", methods=[GET, POST])
@safe_endpoint
def policy(country_id: str, policy_id: str):
    if flask.request.method == GET:
        return get_policy(country_id, policy_id)
    elif flask.request.method == POST:
        policy_json = flask.request.json
        return set_policy(country_id, policy_id, policy_json)

@app.route("/<country_id>/policy", methods=[POST])
@safe_endpoint
def new_policy(country_id: str):
    payload = flask.request.json
    label = payload.get("label")
    policy_json = payload.get("data")
    return set_policy(country_id, None, policy_json, label=label)

@app.route("/<country_id>/household/<household_id>/policy/<policy_id>", methods=[GET])
@safe_endpoint
def compute(country_id: str, household_id: str, policy_id: str):
    if policy_id == "current-law":
        policy_id = get_current_law_policy_id(country_id)
    return get_household_under_policy(country_id, household_id, policy_id)


# Search endpoint for policies
@app.route("/<country_id>/policies", methods=[GET])
def search_policy(country_id: str):
    query = flask.request.args.get("query")
    return search_policies(country_id, query)


@app.route("/<country_id>/economy/<policy_id>", methods=[GET])
@app.route(
    "/<country_id>/economy/<policy_id>/over/<baseline_policy_id>", methods=[GET]
)
def economy(
    country_id: str, policy_id: str = None, baseline_policy_id: str = None
):
    country = countries.get(country_id)
    if country is None:
        return flask.Response(f"Country {country_id} not found.", status=404)

    if baseline_policy_id is None:
        baseline_policy_id = get_current_law_policy_id(country_id)

    reform_policy = database.get_in_table("policy", country_id=country_id, policy_id=policy_id)
    baseline_policy = database.get_in_table("policy", country_id=country_id, policy_id=baseline_policy_id)

    if reform_policy is None:
        return flask.Response(dict(status="error", message=f"Reform policy {policy_id} not found."), status=404)
    
    if baseline_policy is None:
        return flask.Response(dict(status="error", message=f"Baseline policy {baseline_policy_id} not found."), status=404)

    query_parameters = flask.request.args
    region = query_parameters.get("region")
    time_period = query_parameters.get("time_period")

    body = flask.request.json
    options = body.get("options", {})
    options_json = json.dumps(options)

    reform_impact = database.get_in_table(
        "reform_impact",
        country_id=country_id,
        reform_policy_id=policy_id,
        baseline_policy_id=baseline_policy_id,
        region=region,
        time_period=time_period,
        options_json=options_json,
    )

    if reform_impact is None or reform_impact.get("status") == "computing":
        if reform_impact is None:
            requests.get(
                f"{COMPUTE_API}/{country_id}/compare/{policy_id}/{baseline_policy_id}"
            )
        return dict(
            status="computing",
            message="The impact of this policy is being computed.",
        )

    if reform_impact.get("status") == "error":
        return dict(
            status="error",
            message=reform_impact.get("message"),
        )
    
    return dict(
        status="ok",
        message=None,
        result=json.loads(reform_impact.get("reform_impact_json")),
    )
