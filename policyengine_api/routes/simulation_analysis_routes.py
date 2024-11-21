from flask import Blueprint, request, Response, stream_with_context
from policyengine_api.helpers import validate_country
from policyengine_api.services.simulation_analysis_service import (
    SimulationAnalysisService,
)

simulation_analysis_bp = Blueprint("simulation_analysis", __name__)
simulation_analysis_service = SimulationAnalysisService()


@simulation_analysis_bp.route("", methods=["POST"])
def execute_simulation_analysis(country_id):
    print("Got POST request for simulation analysis")

    # Validate inbound country ID
    invalid_country = validate_country(country_id)
    if invalid_country:
        return invalid_country

    # Pop items from request payload and validate
    # where necessary
    payload = request.json

    is_payload_valid, message = validate_payload(payload)
    if not is_payload_valid:
        return Response(
            status=400, response=f"Invalid JSON data; details: {message}"
        )

    currency: str = payload.get("currency")
    selected_version: str = payload.get("selected_version")
    time_period: str = payload.get("time_period")
    impact: dict = payload.get("impact")
    policy_label: str = payload.get("policy_label")
    policy: dict = payload.get("policy")
    region: str = payload.get("region")
    relevant_parameters: list = payload.get("relevant_parameters")
    relevant_parameter_baseline_values: list = payload.get(
        "relevant_parameter_baseline_values"
    )
    audience = payload.get("audience", "")

    try:
        analysis = simulation_analysis_service.execute_analysis(
            country_id,
            currency,
            selected_version,
            time_period,
            impact,
            policy_label,
            policy,
            region,
            relevant_parameters,
            relevant_parameter_baseline_values,
            audience,
        )

        # Create streaming response
        response = Response(
            stream_with_context(analysis),
            status=200,
        )

        # Set header to prevent buffering on Google App Engine deployment
        # (see https://cloud.google.com/appengine/docs/flexible/how-requests-are-handled?tab=python#x-accel-buffering)
        response.headers["X-Accel-Buffering"] = "no"

        return response
    except Exception as e:
        return {
            "status": "error",
            "message": "An error occurred while executing the simulation analysis. Details: "
            + str(e),
            "result": None,
        }, 500


def validate_payload(payload: dict):
    # Check if all required keys are present; note
    # that the audience key is optional
    required_keys = [
        "currency",
        "selected_version",
        "time_period",
        "impact",
        "policy_label",
        "policy",
        "region",
        "relevant_parameters",
        "relevant_parameter_baseline_values",
    ]
    str_keys = [
        "currency",
        "selected_version",
        "time_period",
        "policy_label",
        "region",
    ]
    dict_keys = [
        "policy",
        "impact",
    ]
    list_keys = ["relevant_parameters", "relevant_parameter_baseline_values"]
    missing_keys = [key for key in required_keys if key not in payload]
    if missing_keys:
        return False, f"Missing required keys: {missing_keys}"

    # Check if all keys are of the right type
    for key, value in payload.items():
        if key in str_keys and not isinstance(value, str):
            return False, f"Key '{key}' must be a string"
        elif key in dict_keys and not isinstance(value, dict):
            return False, f"Key '{key}' must be a dictionary"
        elif key in list_keys and not isinstance(value, list):
            return False, f"Key '{key}' must be a list"

    return True, None
