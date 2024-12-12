from flask import Blueprint, request, Response, stream_with_context
from policyengine_api.utils.payload_validators import (
    validate_country,
    validate_tracer_analysis_payload,
)
from policyengine_api.services.tracer_analysis_service import (
    TracerAnalysisService,
)
import json

tracer_analysis_bp = Blueprint("tracer_analysis", __name__)
tracer_analysis_service = TracerAnalysisService()


@tracer_analysis_bp.route("/<country_id>/tracer-analysis", methods=["POST"])
@validate_country
def execute_tracer_analysis(country_id):

    payload = request.json

    is_payload_valid, message = validate_tracer_analysis_payload(payload)
    if not is_payload_valid:
        return Response(
            status=400, response=f"Invalid JSON data; details: {message}"
        )

    household_id = payload.get("household_id")
    policy_id = payload.get("policy_id")
    variable = payload.get("variable")

    try:
        # Create streaming response
        response = Response(
            stream_with_context(
                tracer_analysis_service.execute_analysis(
                    country_id,
                    household_id,
                    policy_id,
                    variable,
                )
            ),
            status=200,
        )

        # Set header to prevent buffering on Google App Engine deployment
        # (see https://cloud.google.com/appengine/docs/flexible/how-requests-are-handled?tab=python#x-accel-buffering)
        response.headers["X-Accel-Buffering"] = "no"

        return response
    except KeyError as e:
        """
        This exception is raised when the tracer can't find a household tracer record
        """
        return Response(
            json.dumps(
                {
                    "status": "not found",
                    "message": "No household simulation tracer found",
                    "result": None,
                }
            ),
            404,
        )
    except Exception as e:
        return Response(
            json.dumps(
                {
                    "status": "error",
                    "message": "An error occurred while executing the tracer analysis. Details: "
                    + str(e),
                    "result": None,
                }
            ),
            500,
        )
