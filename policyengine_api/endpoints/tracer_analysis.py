from policyengine_api.data import local_database
import json
from flask import Response, request
from policyengine_api.country import validate_country
import sys
from policyengine_api.endpoints.analysis import get_analysis

# Rename the file and get_tracer method to something more logical
# Change the database call to select based only on household_id, policy_id, and country_id (Done)
# Add a placeholder for a parsing function (to be completed later) – ideally, have it return some sample output
# Access the prompt and add the parsed tracer output
# Pass the complete prompt to the get_analysis function and return its response

#TODO: Add the prompt in a new variable; this could even be duplicated from the Streamlit

def trigger_tracer_analysis(
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

    # Retrieve from the tracers table in the local database
    row = local_database.query(
        """
        SELECT * FROM tracers 
        WHERE household_id = ? AND policy_id = ? AND country_id = ?
        """,
        (household_id, policy_id, country_id),
    ).fetchone()

    # TODO: Parser for the tracer output
    # TODO: Add the parsed tracer output to the prompt
    # TODO: Call get_analysis with the complete prompt

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