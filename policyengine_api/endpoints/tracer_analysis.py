from policyengine_api.data import local_database
import json
from flask import Response, request, stream_with_context
from policyengine_api.helpers import validate_country
from policyengine_api.ai_prompts import tracer_analysis_prompt
from policyengine_api.utils.ai_analysis import (
    trigger_ai_analysis,
    get_existing_analysis,
)
from policyengine_api.utils.tracer_analysis import parse_tracer_output
from policyengine_api.country import COUNTRY_PACKAGE_VERSIONS
from typing import Generator

# Rename the file and get_tracer method to something more logical (Done)
# Change the database call to select based only on household_id, policy_id, and country_id (Done)
# Add a placeholder for a parsing function (to be completed later) – ideally, have it return some sample output
# Access the prompt and add the parsed tracer output
# Pass the complete prompt to the get_analysis function and return its response

# TODO: Add the prompt in a new variable; this could even be duplicated from the Streamlit


def execute_tracer_analysis(
    country_id: str,
):
    """Get a tracer from the local database.

    Args:
        country_id (str): The country ID.
    """

    country_not_found = validate_country(country_id)
    if country_not_found:
        return country_not_found

    payload = request.json

    household_id = payload.get("household_id")
    policy_id = payload.get("policy_id")
    variable = payload.get("variable")

    api_version = COUNTRY_PACKAGE_VERSIONS[country_id]

    # Retrieve from the tracers table in the local database
    row = local_database.query(
        """
        SELECT * FROM tracers 
        WHERE household_id = ? AND policy_id = ? AND country_id = ? AND api_version = ?
        """,
        (household_id, policy_id, country_id, api_version),
    ).fetchone()

    # Fail if no tracer found
    if row is None:
        return Response(
            status=404,
            response={
                "message": "Unable to analyze household: no household simulation tracer found",
            },
        )

    # Parse the tracer output
    tracer_output_list = json.loads(row["tracer_output"])
    try:
        tracer_segment = parse_tracer_output(tracer_output_list, variable)
    except Exception as e:
        return Response(
            status=500,
            response={
                "message": "Error parsing tracer output",
                "error": str(e),
            },
        )

    # Add the parsed tracer output to the prompt
    prompt = tracer_analysis_prompt.format(
        variable=variable, tracer_segment=tracer_segment
    )

    # If a calculated record exists for this prompt, return it as a
    # streaming response
    existing_analysis: Generator = get_existing_analysis(prompt)
    if existing_analysis is not None:
        return Response(stream_with_context(existing_analysis), status=200)

    # Otherwise, pass prompt to Claude, then return streaming function
    try:
        analysis: Generator = trigger_ai_analysis(prompt)
        return Response(stream_with_context(analysis), status=200)
    except Exception as e:
        return Response(
            status=500,
            response={
                "message": "Error computing analysis",
                "error": str(e),
            },
        )
