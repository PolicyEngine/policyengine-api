from flask import Blueprint, request, Response, stream_with_context
from werkzeug.exceptions import BadRequest
from policyengine_api.utils.payload_validators import validate_country
from policyengine_api.services.simulation_analysis_service import (
    SimulationAnalysisService,
)
from policyengine_api.utils.payload_validators import (
    validate_country,
)
from policyengine_api.utils.payload_validators.ai import (
    validate_sim_analysis_payload,
)

simulation_analysis_bp = Blueprint("simulation_analysis", __name__)
simulation_analysis_service = SimulationAnalysisService()


@simulation_analysis_bp.route(
    "/<country_id>/simulation-analysis", methods=["POST"]
)
@validate_country
def execute_simulation_analysis(country_id):
    print("Got POST request for simulation analysis")

    # Pop items from request payload and validate
    # where necessary
    payload = request.json

    is_payload_valid, message = validate_sim_analysis_payload(payload)
    if not is_payload_valid:
        raise BadRequest(f"Invalid JSON data; details: {message}")

    currency: str = payload.get("currency")
    selected_version: str = payload.get("selected_version")
    time_period: str = payload.get("time_period")
    impact: dict = payload.get("impact")
    policy_label: str = payload.get("policy_label")
    policy: dict = payload.get("policy")
    region: str = payload.get("region")
    relevant_parameters: list[dict] = payload.get("relevant_parameters")
    relevant_parameter_baseline_values: list[dict] = payload.get(
        "relevant_parameter_baseline_values"
    )
    audience = payload.get("audience", "")

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
