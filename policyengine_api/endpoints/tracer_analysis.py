from policyengine_api.data import local_database
import json
from flask import Response, request
from policyengine_api.country import validate_country
from policyengine_api.endpoints.analysis import get_analysis
import re
import anthropic

# Rename the file and get_tracer method to something more logical (Done)
# Change the database call to select based only on household_id, policy_id, and country_id (Done)
# Add a placeholder for a parsing function (to be completed later) – ideally, have it return some sample output
# Access the prompt and add the parsed tracer output
# Pass the complete prompt to the get_analysis function and return its response

#TODO: Add the prompt in a new variable; this could even be duplicated from the Streamlit

def get_tracer_analysis(
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
    variable = request.args.get("variable")

    # Retrieve from the tracers table in the local database
    row = local_database.query(
        """
        SELECT * FROM tracers 
        WHERE household_id = ? AND policy_id = ? AND country_id = ?
        """,
        (household_id, policy_id, country_id),
    ).fetchone()

    # TODO: Parser for the tracer output
    tracer_segment = parse_tracer_output(row["tracer_output"], variable)

    # TODO: Add the parsed tracer output to the prompt
    prompt = f"""{anthropic.HUMAN_PROMPT} You are an AI assistant explaining US policy calculations. 
    The user has run a simulation for the variable '{variable}'.
    Here's the tracer output:
    {tracer_segment}
    
    Please explain this result in simple terms. Your explanation should:
    1. Briefly describe what {variable} is.
    2. Explain the main factors that led to this result.
    3. Mention any key thresholds or rules that affected the calculation.
    4. If relevant, suggest how changes in input might affect this result.
    
    Keep your explanation concise but informative, suitable for a general audience. Do not start with phrases like "Certainly!" or "Here's an explanation. It will be rendered as markdown, so preface $ with \.

    {anthropic.AI_PROMPT}"""

    # get prompt_id
    prompt_id = local_database.query(
        """
        SELECT prompt_id FROM analysis WHERE prompt = ?
        """,
        (prompt,),
    ).fetchone()

    # TODO: Call get_analysis with the complete prompt
    analysis = get_analysis(country_id, prompt_id)

    if row is not None:
        tracer = dict(row)
        tracer["tracer_output"] = json.loads(tracer["tracer_output"])
        return dict(
            status=200,
            message=None,
            result=analysis,
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
