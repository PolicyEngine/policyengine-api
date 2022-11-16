"""
The Compute API is a separate Flask app that runs on a separate port. 
It is designed to be run on a separate server from the main PolicyEngine web app, so that it can
be used for compute-intensive tasks without affecting the main server.
"""

import flask
from flask_cors import CORS
from policyengine_api.constants import GET, POST, __version__
from policyengine_api.country import PolicyEngineCountry
from policyengine_api.data import PolicyEngineDatabase
from multiprocessing import Process

app = flask.Flask(__name__)

CORS(app)

uk = PolicyEngineCountry("policyengine_uk", "uk")
us = PolicyEngineCountry("policyengine_us", "us")
countries = dict(uk=uk, us=us)

database = PolicyEngineDatabase()

@app.route("/", methods=[GET])
def home():
    return f"<h1>PolicyEngine compute API v{__version__}</h1><p>Use this API to compute the impact of public policy on economies.</p>"

@app.route("/<country_id>/<policy_id>", methods=[GET])
def score_policy_reform(country_id: str, policy_id: str) -> dict:
    """
    The /score_policy_reform endpoint is designed for the PolicyEngine web app. It computes the impact of a policy reform
    on an economy.

    Args:
        country_id (str): The country ID. Currently supported countries are the UK and the US.
        policy_id (str): The policy ID.

    Returns:
        dict: The results of the computation.
    """

    policy = database.get_policy(policy_id)
    if policy is None:
        return flask.Response(f"Policy {policy_id} not found.", status=404)
    
    country = countries.get(country_id)
    if country is None:
        return flask.Response(f"Country {country_id} not found.", status=404)

    # Insert a new row into the database (designated as incomplete)

    database.set_economy({}, country_id, policy_id, False)

    task = Process(target=set_reform_impact, args=(database, policy_id, country_id))

    task.start()

    return {
        "status": "success",
        "policy_id": policy_id,
        "country_id": country_id,
    }

def set_reform_impact(database: PolicyEngineDatabase, policy_id: int, country_id: str) -> None:
    """
    Syncronously computes the impact of a policy reform on an economy.

    Args:
        database (PolicyEngineDatabase): The database.
        policy_id (int): The policy ID.
        country_id (str): The country ID. Currently supported countries are the UK and the US.
    """

    policy = database.get_policy(policy_id)
    if policy is None:
        return flask.Response(f"Policy {policy_id} not found.", status=404)
    
    country = countries.get(country_id)
    if country is None:
        return flask.Response(f"Country {country_id} not found.", status=404)
    return country.score_reform(policy)