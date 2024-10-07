from policyengine_api.data import local_database
from policyengine_api.utils import hash_object
from flask import request, Response
from rq import Queue
from redis import Redis
from typing import Optional
from policyengine_api.utils.ai_analysis import (
    trigger_ai_analysis,
    get_existing_analysis,
)
from policyengine_api.ai_prompts import (
    generate_simulation_analysis_prompt,
    audience_descriptions,
)

queue = Queue(connection=Redis())


def execute_simulation_analysis(country_id: str) -> Response:

    # Pop the various parameters from the request
    payload = request.json

    currency = payload.get("currency")
    selected_version = payload.get("selected_version")
    time_period = payload.get("time_period")
    impact = payload.get("impact")
    policy_label = payload.get("policy_label")
    policy = payload.get("policy")
    region = payload.get("region")
    relevant_parameters = payload.get("relevant_parameters")
    relevant_parameter_baseline_values = payload.get(
        "relevant_parameter_baseline_values"
    )
    audience = payload.get("audience")

    # Check if the region is enhanced_cps
    is_enhanced_cps = "enhanced_cps" in region

    # Create prompt based on data
    prompt = generate_simulation_analysis_prompt(
        time_period,
        region,
        currency,
        policy,
        impact,
        relevant_parameters,
        relevant_parameter_baseline_values,
        is_enhanced_cps,
        selected_version,
        country_id,
        policy_label,
    )

    # Add audience description to end
    prompt += audience_descriptions[audience]

    # If a calculated record exists for this prompt, return it as a
    # streaming response
    existing_analysis = get_existing_analysis(prompt)
    if existing_analysis is not None:
        return Response(status=200, response=existing_analysis)

    # Otherwise, pass prompt to Claude, then return streaming function
    try:
        analysis = trigger_ai_analysis(prompt)
        return Response(status=200, response=analysis)
    except Exception as e:
        return Response(
            status=500,
            response={
                "message": "Error computing analysis",
                "error": str(e),
            },
        )
