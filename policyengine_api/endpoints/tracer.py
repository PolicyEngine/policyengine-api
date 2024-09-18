from policyengine_api.data import local_database
import json
from flask import Response, request
from policyengine_api.country import validate_country
import sys


def get_tracer(
    country_id: str,
):
    """Get a tracer from the local database.

    Args:
        country_id (str): The country ID.
    """

    country_not_found = validate_country(country_id)
    if country_not_found:
        return country_not_found

    household_id = request.args.get("household_id")
    policy_id = request.args.get("policy_id")
    variable_name = request.args.get("variable_name")

    # Retrieve from the tracers table in the local database
    row = local_database.query(
        """
        SELECT * FROM tracers 
        WHERE household_id = ? AND policy_id = ? AND country_id = ? AND variable_name = ?
        """,
        (household_id, policy_id, country_id, variable_name),
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
            message="Tracer not found.",
        )
        return Response(
            json.dumps(response_body),
            status=404,
            mimetype="application/json",
        )
