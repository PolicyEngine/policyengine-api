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

uk = PolicyEngineCountry("policyengine_uk", "uk")
us = PolicyEngineCountry("policyengine_us", "us")
countries = dict(uk=uk, us=us)

database = PolicyEngineDatabase()

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
        policy_id = "current-law"
    else:
        policy_id = database.get_policy_id(policy)

    household_id = database.get_household_id(household, country_id, label=policy_id)

    pre_computed_household = database.get_computed_household(
        household_id, policy_id, country_id
    )

    if pre_computed_household is not None:
        return pre_computed_household
    else:
        computed_household = country.calculate(household, policy)
        database.set_computed_household(
            computed_household, household_id, policy_id, country_id
        )
        return computed_household

@app.route("/<country_id>/economy", methods=[POST])
@app.route("/<country_id>/economy/<policy_id>", methods=[GET])
def economy(country_id: str, policy_id: str = None):
    country = countries.get(country_id)
    if country is None:
        return flask.Response(f"Country {country_id} not found.", status=404)
    if flask.request.method == POST:
        database.set_policy(policy_id, flask.request.get_json())
    
    # Send a request to the compute API to compute the impact of the policy reform on the economy.

    economy_data = database.get_economy(country_id, policy_id)

    if economy_data is not None:
        return economy_data

    response = requests.get(f"{COMPUTE_API}/{country_id}/{policy_id}")

    return response.json()

