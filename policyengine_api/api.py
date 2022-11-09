import flask
from flask_cors import CORS
from time import time
import json
from policyengine_api.constants import GET, POST, __version__
from policyengine_api.country import PolicyEngineCountry
from policyengine_api.data import PolicyEngineData
from policyengine_api.utils import hash_object

app = flask.Flask(__name__)

CORS(app)

uk = PolicyEngineCountry("policyengine_uk", "uk")
us = PolicyEngineCountry("policyengine_us", "us")
countries = dict(uk=uk, us=us)
database = PolicyEngineData()


@app.route("/", methods=[GET])
def home():
    return f"<h1>PolicyEngine households API v{__version__}</h1><p>Use this API to compute the impact of public policy on individual households.</p>"

@app.route("/<country_id>/metadata", methods=[GET])
def metadata(country_id: str):
    country = countries.get(country_id)
    if country is None:
        return flask.Response(f"Country {country_id} not found.", status=404)
    return {
        "variables": country.build_variables(),
        "entities": country.build_entities(),
        "parameters": country.build_parameters(),
        "variableModules": country.variable_module_metadata,
    }
    

@app.route("/<country_id>/variables", methods=[GET])
def variables(country_id: str):
    country = countries.get(country_id)
    if country is None:
        return flask.Response(f"Country {country_id} not found.", status=404)
    return country.variable_data

@app.route("/<country_id>/parameters", methods=[GET])
def parameters(country_id: str):
    country = countries.get(country_id)
    if country is None:
        return flask.Response(f"Country {country_id} not found.", status=404)
    return country.parameter_data

@app.route("/<country_id>/entities", methods=[GET])
def entities(country_id: str):
    country = countries.get(country_id)
    if country is None:
        return flask.Response(f"Country {country_id} not found.", status=404)
    return country.entities_data

@app.route("/<country_id>/household", methods=[GET, POST])
@app.route("/<country_id>/household/<household_id>", methods=[GET, POST])
def household(country_id: str, household_id: str = None):
    country = countries.get(country_id)
    if country is None:
        return flask.Response(f"Country {country_id} not found.", status=404)
    if flask.request.method == POST:
        household = flask.request.get_json()
        household_object = {
            "household_str": json.dumps(household),
            "country_id": country_id,
            "label": f"Household #{len(database.household_table)}",
            "household_policy_ids": [],
            "household_axis_policy_ids": [],
        }
        if household_id is None:
            household_id = str(len(database.household_table))
        
        if country_id + "-" + household_id in database.household_table:
            household_policy_ids = database.household_table[country_id + "-" + household_id]["household_policy_ids"]
            for household_policy_id in household_policy_ids:
                if country_id + "-" + household_policy_id in database.household_policy_table:
                    del database.household_policy_table[country_id + "-" + household_policy_id]

        database.household_table[country_id + "-" + household_id] = household_object
        return {
            "household_id": household_id,
        }
    else:
        if household_id is None:
            # Return 400 bad request
            return flask.Response(status=400, response="No household ID provided.")
        household = json.loads(json.dumps(database.household_table.get(country_id + "-" + household_id)))
        if household is None:
            # Return 404 not found
            return flask.Response(status=404, response=f"Household {household_id} not found.")
        household["household"] = json.loads(household["household_str"])
        del household["household_str"]
        return household


@app.route("/<country_id>/policy", methods=[GET, POST])
@app.route("/<country_id>/policy/<policy_id>", methods=[GET, POST])
def policy(country_id: str, policy_id: str = None):
    country = countries.get(country_id)
    if country is None:
        return flask.Response(f"Country {country_id} not found.", status=404)
    if flask.request.method == POST:
        policy = flask.request.get_json()
        policy_object = {
            "policy": policy,
            "country_id": country_id,
        }
        if policy_id is None:
            policy_id = hash_object(policy_object)
        database.policy_table[country_id + "-" + policy_id] = policy_object
        return {
            "policy_id": policy_id,
        }
    else:
        if policy_id is None:
            # Return 400 bad request
            return flask.Response(status=400, response="No policy ID provided.")
        household = database.policy_table.get(country_id + "-" + policy_id)
        if household is None:
            # Return 404 not found
            return flask.Response(status=404, response=f"Household {policy_id} not found.")
        return household

@app.route("/<country_id>/household/<household_id>/<policy_id>", methods=[GET])
@app.route("/<country_id>/household/<household_id>/<policy_id>/<entity_type_id>", methods=[GET])
@app.route("/<country_id>/household/<household_id>/<policy_id>/<entity_type_id>/<entity_id>", methods=[GET])
@app.route("/<country_id>/household/<household_id>/<policy_id>/<entity_type_id>/<entity_id>/<variable>", methods=[GET])
@app.route("/<country_id>/household/<household_id>/<policy_id>/<entity_type_id>/<entity_id>/<variable>/<period>", methods=[GET])
def household_under_policy(
    country_id: str,
    household_id: str,
    policy_id: str,
    entity_type_id: str = None,
    entity_id: str = None,
    variable: str = None,
    period: str = None,
):
    country = countries.get(country_id)
    if country is None:
        return flask.Response(f"Country {country_id} not found.", status=404)
    household = database.household_table.get(country_id + "-" + household_id)
    if household is None:
        return flask.Response(f"Household {household_id} not found.", status=404)
    policy = database.policy_table.get(country_id + "-" + policy_id)
    if policy is None:
        return flask.Response(f"Policy {policy_id} not found.", status=404)

    axis_variable = flask.request.args.get("axis_variable")
    axis_period = flask.request.args.get("axis_period")
    axis_min = flask.request.args.get("axis_min")
    axis_max = flask.request.args.get("axis_max")
    axis_count = flask.request.args.get("axis_count")

    household_policy_id = f"{household_id}_{policy_id}"

    if axis_variable is not None:
        axis = dict(
            name=axis_variable,
            period=axis_period,
            min=int(axis_min),
            max=int(axis_max),
            count=int(axis_count),
        )
        household_policy_id += f"_axis_{axis_variable}_{axis_period}_{axis_min}_{axis_max}_{axis_count}"
    else:
        axis = None

    household_policy = database.household_policy_table.get(country_id + "-" + household_policy_id)

    if household_policy not in database.household_table.get(country_id + "-" + household_id)["household_policy_ids"]:
        database.household_table.get(country_id + "-" + household_id)["household_policy_ids"].append(household_policy_id)

    if household_policy is None:
        # We have saved the household, but not calculated its results under this policy. Do so now.
        household_str = json.dumps(country.calculate(json.loads(household["household_str"]), policy["policy"], axis=axis))
        household_policy = {
            "household_str": household_str,
            "country_id": country_id,
            "household_id": household_id,
            "policy_id": policy_id,
        }
        database.household_policy_table[country_id + "-" + household_policy_id] = household_policy
    
    household_data = json.loads(household_policy["household_str"])

    if entity_type_id is None:
        return household_data
    if entity_type_id not in household_data:
        return flask.Response(f"Entity type {entity_type_id} not found.", status=404)
    
    entity_type = household_data[entity_type_id]

    if entity_id is None:
        return entity_type
    if entity_id not in entity_type:
        return flask.Response(f"Entity {entity_id} not found.", status=404)
    
    entity = entity_type[entity_id]

    if variable is None:
        return entity
    if period is not None:
        # Add to the household table entry
        household_input = json.loads(database.household_table.get(country_id + "-" + household_id)["household_str"])
        variable_data = household_input[entity_type_id][entity_id].get(variable, {})
        if period not in variable_data:
            variable_data[period] = None
        variable_data[period] = None
        database.household_table[country_id + "-" + household_id]["household_str"] = json.dumps(household_input)

        household_input[entity_type_id][entity_id][variable] = {period: None}
        computed_household_data = country.calculate(household_input, policy["policy"], axis=axis)

        household_policy["household_str"] = json.dumps(computed_household_data)

        database.household_policy_table[country_id + "-" + household_policy_id] = household_policy

        return dict(value=computed_household_data[entity_type_id][entity_id][variable][period])
    if variable not in entity:
        return flask.Response(f"Variable {variable} for entity {entity_id} not found.", status=404)
    
    variable_data = entity[variable]

    if period is None:
        return variable_data
    if period not in variable_data:
        return flask.Response(f"Period {period} for variable {variable} in entity {entity_id} not found.", status=404)
        
