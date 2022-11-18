import flask
import requests
from flask_cors import CORS
from policyengine_api.constants import GET, POST, __version__
from policyengine_api.country import PolicyEngineCountry
from policyengine_api.utils import hash_object
from policyengine_api.data import PolicyEngineDatabase
from policyengine_api.repo import VERSION

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
    return f"<h1>PolicyEngine households API v{__version__}</h1><p>Use this API to compute the impact of public policy on individual households.</p>"


@app.route("/<country_id>/metadata", methods=[GET])
def metadata(country_id: str):
    """
    The /metadata endpoint is designed for the PolicyEngine web app. It contains all the information needed by the UI
    for a single country.

    Args:
        country_id (str): The country ID. Currently supported countries are the UK and the US.

    Returns:

    """
    country = countries.get(country_id)
    if country is None:
        return flask.Response(f"Country {country_id} not found.", status=404)
    return {
        "variables": country.build_variables(),
        "entities": country.build_entities(),
        "parameters": country.build_parameters(),
        "variableModules": country.variable_module_metadata,
    }


@app.route("/<country_id>/calculate", methods=[POST])
def calculate(country_id: str):
    country = countries.get(country_id)
    if country is None:
        return flask.Response(f"Country {country_id} not found.", status=404)
    household = flask.request.get_json()
    policy = household.pop("policy", {})

    if len(policy.keys()) == 0:
        policy_id = 1
    else:
        policy_id = database.get_policy_id(policy, country_id)

    household_id = database.get_household_id(household, country_id)

    pre_computed_household = database.get_computed_household(
        household_id, policy_id, country_id
    )

    if pre_computed_household is not None:
        return {**pre_computed_household, "household_id": household_id}
    else:
        computed_household = country.calculate(household, policy)
        database.set_computed_household(
            computed_household, household_id, policy_id, country_id
        )
        return {**computed_household, "household_id": household_id}


@app.route("/<country_id>/policy", methods=[POST])
@app.route("/<country_id>/policy/<policy_id>", methods=[GET])
def policy(country_id: str, policy_id: int = None):
    if flask.request.method == "POST":
        policy = flask.request.get_json()
        policy_id = database.get_policy_id(policy, country_id)
        return {"policy_id": policy_id, "policy": policy}
    else:
        policy = database.get_policy(policy_id, country_id)
        return policy


@app.route("/<country_id>/household", methods=[POST])
@app.route("/<country_id>/household/<household_id>", methods=[GET])
def household(country_id: str, household_id: int = None):
    if flask.request.method == "POST":
        household = flask.request.get_json()
        household_id = database.get_household_id(household, country_id)
        return {"household_id": household_id}
    else:
        household = database.get_household(household_id, country_id)
        if household is None:
            return flask.Response(
                f"Household {household_id} not found.", status=404
            )
        return household


@app.route("/<country_id>/economy/<policy_id>", methods=[GET])
@app.route(
    "/<country_id>/economy/<policy_id>/<baseline_policy_id>", methods=[GET]
)
def economy(
    country_id: str, policy_id: str = None, baseline_policy_id: str = None
):
    country = countries.get(country_id)
    if country is None:
        return flask.Response(f"Country {country_id} not found.", status=404)

    if baseline_policy_id is None:
        baseline_policy_id = (
            1  # 1 is always the ID of the current law policy in the database.
        )

    if not database.has_policy_id(country_id, baseline_policy_id):
        return flask.Response(
            f"Policy {baseline_policy_id} not found.", status=404
        )

    if not database.has_policy_id(country_id, policy_id):
        return flask.Response(f"Policy {policy_id} not found.", status=404)

    impact, stable = database.get_reform_impact(
        country_id, baseline_policy_id, policy_id
    )

    if impact is None:
        if stable:
            requests.get(
                f"{COMPUTE_API}/{country_id}/compare/{policy_id}/{baseline_policy_id}"
            )
        return {"status": "computing"}

    return {
        "status": "complete",
        **impact,
    }
