from policyengine_api.data import database
import json
from flask import Response

def get_tracer(country_id: str, household_id: int, api_version: str, variable_name: str, policy_id: int):
    """ Get a tracer from the database.

    Args:
        country_id (str): The country ID.
        household_id (str): The household ID.
        policy_id (str): The policy ID.
        api_version (str): The API version.
        variable_name (str): The variable name.
        policy_id (int): The policy ID.
    """
    # Retrieve from the tracers table
    row = database.query(
        f"SELECT * FROM tracers WHERE household_id = ? AND country_id = ? AND api_version = ? AND variable_name = ? AND policy_id = ?",
        (household_id, country_id, api_version, variable_name, policy_id),
    ).fetchone()
    
    if row is not None:
        tracer = dict(row)
        tracer["tracer_output"] = json.loads(tracer["tracer_output"])
        return dict(
            status=200,
            message=None,
            result=tracer,
        )
    else:
        response_body = dict(
            status="error",
            message=f"Tracer not found.",
        )
        return Response(
            json.dumps(response_body),
            status=404,
            mimetype="application/json",
        )