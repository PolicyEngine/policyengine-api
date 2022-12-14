import flask
import requests
from flask_cors import CORS
import json
from pathlib import Path
import os
import datetime
from policyengine_api.constants import GET, POST, LIST, UPDATE, REPO, VERSION
from policyengine_api.country import PolicyEngineCountry, COUNTRIES
from policyengine_api.utils import hash_object, safe_endpoint
from policyengine_api.data import PolicyEngineDatabase, database
from policyengine_api.endpoints import (
    metadata,
    get_household,
    set_household,
    get_policy,
    set_policy,
    get_household_under_policy,
    search_policies,
    get_current_law_policy_id,
)

app = application = flask.Flask(__name__)

CORS(app)

uk = PolicyEngineCountry("policyengine_uk")
us = PolicyEngineCountry("policyengine_us")
countries = dict(uk=uk, us=us)

debug = False

if debug:
    HOST = "127.0.0.1"
    API_PORT = 5000
    COMPUTE_API_PORT = 5001
    API = f"http://{HOST}:{API_PORT}"
    COMPUTE_API = f"http://{HOST}:{COMPUTE_API_PORT}"
else:
    COMPUTE_API = "https://compute.api.policyengine.org"

database.initialize()


@app.route("/", methods=[GET])
def home():
    return f"<h1>PolicyEngine households API v{VERSION}</h1><p>Use this API to compute the impact of public policy on individual households.</p>"


@app.route("/<country_id>/metadata", methods=[GET])
@safe_endpoint
def get_metadata(country_id: str):
    return metadata(country_id)


@app.route("/<country_id>/household/<household_id>", methods=[GET, POST])
@safe_endpoint
def household(country_id: str, household_id: str):
    household_id = int(household_id)
    if flask.request.method == GET:
        return get_household(country_id, household_id=household_id)
    elif flask.request.method == POST:
        payload = flask.request.json
        label = payload.get("label")
        household_json = payload.get("data")
        return set_household(
            country_id, household_id, household_json, label=label
        )


@app.route("/<country_id>/household", methods=[POST])
@safe_endpoint
def new_household(country_id: str):
    payload = flask.request.json
    label = payload.get("label")
    household_json = payload.get("data")
    household_hash = hash_object(household_json)
    existing_household = database.get_in_table(
        "household",
        country_id=country_id,
        household_hash=household_hash,
    )
    if existing_household:
        return dict(
            status="ok",
            result=dict(
                household_id=existing_household["id"],
            ),
        )
    else:
        return set_household(country_id, None, household_json, label=label)


@app.route("/<country_id>/policy/<policy_id>", methods=[GET, POST])
@safe_endpoint
def policy(country_id: str, policy_id: str):
    if policy_id == "current-law":
        policy_id = get_current_law_policy_id(country_id)
    if flask.request.method == GET:
        policy_id = int(policy_id)
        return get_policy(country_id, policy_id)
    elif flask.request.method == POST:
        policy_json = flask.request.json
        return set_policy(country_id, policy_id, policy_json)


@app.route("/<country_id>/policy", methods=[POST])
@safe_endpoint
def new_policy(country_id: str):
    payload = flask.request.json
    label = payload.pop("label", None)
    policy_json = payload.pop("data", None)
    return set_policy(country_id, None, policy_json, label=label)


@app.route(
    "/<country_id>/household/<household_id>/policy/<policy_id>", methods=[GET]
)
@safe_endpoint
def compute(country_id: str, household_id: str, policy_id: str):
    if policy_id == "current-law":
        policy_id = get_current_law_policy_id(country_id)
    household_id = int(household_id)
    policy_id = int(policy_id)
    return get_household_under_policy(country_id, household_id, policy_id)


@app.route("/<country_id>/calculate", methods=[POST])
@safe_endpoint
def calculate(country_id: str):
    payload = flask.request.json
    household = payload.pop("household", None)
    if household is None:
        return flask.Response(
            json.dumps(dict(error="No household provided.", status="error")),
            status=400,
        )
    household_id = None
    policy = payload.pop("policy", None)
    policy_id = payload.pop("policy_id", None)
    if policy_id is None:
        if policy is not None:
            policy_id = set_policy(country_id, None, policy)["result"][
                "policy_id"
            ]
        else:
            policy_id = get_current_law_policy_id(country_id)
    elif policy_id == "current-law":
        policy_id = get_current_law_policy_id(country_id)
    if household is not None:
        household_id = set_household(country_id, None, household)["result"][
            "household_id"
        ]
    return get_household_under_policy(country_id, household_id, policy_id)


# Search endpoint for policies
@app.route("/<country_id>/policies", methods=[GET, POST])
@safe_endpoint
def search_policy(country_id: str):
    query = flask.request.args.get("query")
    return search_policies(country_id, query)


@app.route("/<country_id>/economy/<policy_id>", methods=[GET])
@app.route(
    "/<country_id>/economy/<policy_id>/over/<baseline_policy_id>",
    methods=[GET],
)
def economy(
    country_id: str, policy_id: str = None, baseline_policy_id: str = None
):
    policy_id = int(policy_id)
    baseline_policy_id = int(baseline_policy_id)
    if policy_id == "current_law":
        policy_id = get_current_law_policy_id(country_id)
    country = COUNTRIES.get(country_id)
    if country is None:
        return flask.Response(f"Country {country_id} not found.", status=404)

    if baseline_policy_id is None or baseline_policy_id == "current-law":
        baseline_policy_id = get_current_law_policy_id(country_id)

    reform_policy = database.get_in_table(
        "policy",
        country_id=country_id,
        id=policy_id,
    )
    baseline_policy = database.get_in_table(
        "policy",
        country_id=country_id,
        id=baseline_policy_id,
    )

    if reform_policy is None:
        return flask.Response(
            dict(
                status="error", message=f"Reform policy {policy_id} not found."
            ),
            status=404,
        )

    if baseline_policy is None:
        return flask.Response(
            dict(
                status="error",
                message=f"Baseline policy {baseline_policy_id} not found.",
            ),
            status=404,
        )

    query_parameters = flask.request.args
    options = dict(query_parameters)
    options = json.loads(json.dumps(options))
    region = options.pop("region", None)
    time_period = options.pop("time_period", None)
    options_hash = hash_object(json.dumps(options))

    # If there is an entry with an "ok" status, delete all without an "ok status"

    query = (
        "SELECT * FROM reform_impact WHERE country_id = %s AND "
        "reform_policy_id = %s AND baseline_policy_id = %s AND "
        "region = %s AND time_period = %s AND options_hash = %s AND "
        "status = 'ok'"
    )

    has_an_ok = database.query(
        query,
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        time_period,
        options_hash,
    )

    if has_an_ok:
        query = (
            "DELETE FROM reform_impact WHERE country_id = %s AND "
            "reform_policy_id = %s AND baseline_policy_id = %s AND "
            "region = %s AND time_period = %s AND options_hash = %s AND "
            "status != 'ok'"
        )
        database.query(
            query,
            country_id,
            policy_id,
            baseline_policy_id,
            region,
            time_period,
            options_hash,
        )

    reform_impact = database.get_in_table(
        "reform_impact",
        country_id=country_id,
        reform_policy_id=policy_id,
        baseline_policy_id=baseline_policy_id,
        region=region,
        time_period=time_period,
        options_hash=options_hash,
        api_version=VERSION,
    )

    if reform_impact is not None:
        start_time_str = reform_impact.get("start_time")
        if isinstance(start_time_str, str):
            start_time = datetime.datetime.strptime(
                start_time_str, "%Y-%m-%d %H:%M:%S.%f"
            )
        else:
            start_time = start_time_str
        # If the computation has been running for more than 5 minutes, restart it
        outdated = (
            reform_impact.get("status") == "computing"
            and (datetime.datetime.now() - start_time).total_seconds() > 300
        )
    else:
        outdated = True

    if (reform_impact is None) or outdated:
        database.set_in_table(
            "reform_impact",
            dict(
                country_id=country_id,
                reform_policy_id=policy_id,
                baseline_policy_id=baseline_policy_id,
                region=region,
                time_period=time_period,
                options_hash=options_hash,
                api_version=VERSION,
            ),
            dict(
                status="computing",
                start_time=datetime.datetime.now(),
                reform_impact_json=json.dumps({}),
                options_json=json.dumps(options),
            ),
        )
        endpoint = f"{COMPUTE_API}/compute"
        requests.post(
            endpoint,
            json=dict(
                country_id=country_id,
                policy_id=policy_id,
                baseline_policy_id=baseline_policy_id,
                region=region,
                time_period=time_period,
                options=options,
            ),
        )
        return dict(
            status="computing",
            message="The impact of this policy is being computed.",
        )

    if reform_impact.get("status") == "error":
        return dict(
            status="error",
            message=reform_impact.get("message"),
            result=json.loads(reform_impact.get("reform_impact_json")),
        )

    if reform_impact.get("status") == "computing":
        return dict(
            status="computing",
            message="The impact of this policy is being computed.",
        )

    return dict(
        status="ok",
        message=None,
        result=json.loads(reform_impact.get("reform_impact_json")),
    )
