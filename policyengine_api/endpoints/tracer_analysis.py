from policyengine_api.data import local_database
import json
from flask import Response, request
from policyengine_api.country import validate_country
import re
from policyengine_api.ai_prompts import tracer_analysis_prompt
from policyengine_api.utils.ai_analysis import trigger_ai_analysis, get_existing_analysis
from policyengine_api.country import COUNTRY_PACKAGE_VERSIONS

# Rename the file and get_tracer method to something more logical (Done)
# Change the database call to select based only on household_id, policy_id, and country_id (Done)
# Add a placeholder for a parsing function (to be completed later) – ideally, have it return some sample output
# Access the prompt and add the parsed tracer output
# Pass the complete prompt to the get_analysis function and return its response

#TODO: Add the prompt in a new variable; this could even be duplicated from the Streamlit

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

    # Parse the tracer output
    tracer_segment = parse_tracer_output(row["tracer_output"], variable)

    # Add the parsed tracer output to the prompt
    prompt = tracer_analysis_prompt.format(
        variable=variable,
        tracer_segment=tracer_segment
    )

    # If a calculated record exists for this prompt, return it as a
    # streaming response
    existing_analysis = get_existing_analysis(prompt)
    if existing_analysis is not None:
        return Response(
            status=200,
            response=existing_analysis
        )

    # Otherwise, pass prompt to Claude, then return streaming function
    try:
        analysis = trigger_ai_analysis(prompt)
        return Response(
            status=200,
            response=analysis
        )
    except Exception as e:
        return Response(
            status=500,
            response={
                "message": "Error computing analysis",
                "error": str(e),
            }
        )

def parse_tracer_output(tracer_output, target_variable):
    result = []
    target_indent = None
    capturing = False
    
    # Create a regex pattern to match the exact variable name
    # This will match the variable name followed by optional whitespace, 
    # then optional angle brackets with any content, then optional whitespace
    pattern = rf'^(\s*)({re.escape(target_variable)})\s*(?:<[^>]*>)?\s*'

    for line in tracer_output:
        # Count leading spaces to determine indentation level
        indent = len(line) - len(line.strip())
        
        # Check if this line matches our target variable
        match = re.match(pattern, line)
        if match and not capturing:
            target_indent = indent
            capturing = True
            result.append(line)
        elif capturing:
            # Stop capturing if we encounter a line with less indentation than the target
            if indent <= target_indent:
                break
            # Capture dependencies (lines with greater indentation)
            result.append(line)

    return result
