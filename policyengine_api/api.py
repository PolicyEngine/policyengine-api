import flask
import json
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

def get_household_id(household_data: dict, country_id: str, label: str = None) -> int:
    """
    Store a household in the database and return its ID if it doesn't already exist.

    Args:
        household_data (dict): A household's data.
        country_id (str): The country ID.
        label (str): The household's label.

    Returns:
        int: The household's ID.
    """
    household_hash = hash_object(household_data)
    # Check if the household already exists in the database using database.query
    household_id = database.query("SELECT id FROM household WHERE household_hash = ?", (household_hash,)).fetchone()
    if household_id is None:
        # If the household doesn't exist, insert it into the database using database.execute.
        # The required fields are: id, country, label, version, household_json, household_hash
        household_id = database.query("INSERT INTO household VALUES (NULL, ?, ?, ?, ?, ?)", (country_id, label, VERSION, json.dumps(household_data), household_hash)).lastrowid
    else:
        household_id = household_id[0]
    return household_id

def get_policy_id(policy_data: dict, country_id: str, label: str = None) -> int:
    """
    Store a policy in the database and return its ID if it doesn't already exist.

    Args:
        policy_data (dict): A policy's data.
        country_id (str): The country ID.
        label (str): The policy's label.

    Returns:
        int: The policy's ID.
    """
    policy_hash = hash_object(policy_data)
    # Check if the policy already exists in the database using database.query
    policy_id = database.query("SELECT id FROM policy WHERE policy_hash = ?", (policy_hash,)).fetchone()
    if policy_id is None:
        # If the policy doesn't exist, insert it into the database using database.execute.
        # The required fields are: id, country, label, version, policy_json, policy_hash
        policy_id = database.query("INSERT INTO policy VALUES (NULL, ?, ?, ?, ?)", (label, country_id, VERSION, json.dumps(policy_data), policy_hash)).lastrowid
    else:
        policy_id = policy_id[0]
    return policy_id

def get_computed_household(household_id: int, policy_id: int, country_id: str) -> dict:
    """
    Get a computed household from the database.

    Args:
        household_id (int): The household's ID.
        policy_id (int): The policy's ID.
        country_id (str): The country ID.

    Returns:
        dict: The computed household's data.
    """
    # Get the computed household from the database using database.query
    computed_household = database.query("SELECT computed_household_json FROM computed_household WHERE household_id = ? AND policy_id = ? AND country = ?", (household_id, policy_id, country_id)).fetchone()
    if computed_household is None:
        return None
    return json.loads(computed_household[0])

def set_computed_household(computed_household_data: dict, household_id: int, policy_id: int, country_id: str) -> None:
    """
    Store a computed household in the database.

    Args:
        computed_household_data (dict): The computed household's data.
        household_id (int): The household's ID.
        policy_id (int): The policy's ID.
        country_id (str): The country ID.
    """
    # If the computed household doesn't exist, insert it into the database using database.execute.
    # The required fields are: household_id, policy_id, country_id, version, computed_household_json
    database.query("INSERT INTO computed_household VALUES (?, ?, ?, ?, ?)", (household_id, policy_id, country_id, VERSION, json.dumps(computed_household_data)))
    
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
        policy_id = get_policy_id(policy)

    household_id = get_household_id(household, country_id, label=policy_id)

    pre_computed_household = get_computed_household(household_id, policy_id, country_id)

    if pre_computed_household is not None:
        return pre_computed_household
    else:
        computed_household = country.calculate(household, policy)
        set_computed_household(computed_household, household_id, policy_id, country_id)
        return computed_household

