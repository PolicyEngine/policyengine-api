from flask import Blueprint, request, Response
from policyengine_api.helpers import validate_country
from policyengine_api.services.tracer_analysis_service import TracerAnalysisService

tracer_analysis_bp = Blueprint("tracer_analysis", __name__)
tracer_analysis_service = TracerAnalysisService()

@tracer_analysis_bp.route("/", methods=["POST"])
def execute_tracer_analysis(country_id):

    # Validate country ID
    country_not_found = validate_country(country_id)
    if country_not_found:
        return country_not_found

    payload = request.json

    is_payload_valid, message = validate_payload(payload)
    if not is_payload_valid:
        return Response(status=400, response=f"Invalid JSON data; details: {message}")

    household_id = payload.get("household_id")
    policy_id = payload.get("policy_id")
    variable = payload.get("variable")

    try:
        analysis = tracer_analysis_service.execute_analysis(
            country_id,
            household_id,
            policy_id,
            variable,
        )

        return Response(status=200, response=analysis)
    except Exception as e:
        return (
            dict(
                status="error",
                message="An error occurred while executing the tracer analysis. Details: "
                + str(e),
                result=None,
            ),
            500,
        )

def validate_payload(payload: dict):
    # Validate payload
    if not payload:
        return False, "No payload provided"

    required_keys = ["household_id", "policy_id", "variable"]
    for key in required_keys:
        if key not in payload:
            return False, f"Missing required key: {key}"

    return True, None