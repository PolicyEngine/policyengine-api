from flask import Blueprint, request, Response
from policyengine_api.helpers import validate_country
from policyengine_api.services.simulation_analysis_service import SimulationAnalysisService

simulation_analysis_bp = Blueprint("simulation_analysis", __name__)
simulation_analysis_service = SimulationAnalysisService()

@simulation_analysis_bp.route("/", methods=["POST"])
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
        return Response(status=400, response=f"Invalid JSON data; details: {message}")

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

        return Response(status=200, response=analysis)
    except Exception as e:
        return (
            dict(
                status="error",
                message="An error occurred while executing the simulation analysis. Details: "
                + str(e),
                result=None,
            ),
            500,
        )

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
    missing_keys = [key for key in required_keys if key not in payload]
    if missing_keys:
        return False, f"Missing required keys: {missing_keys}"

    # Check if all keys are of the right type
    for key, value in payload.items():
        if not isinstance(value, str):
            return False, f"Key '{key}' must be a string"

    return True, None