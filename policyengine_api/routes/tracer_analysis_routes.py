from flask import Blueprint, request, Response, stream_with_context
from werkzeug.exceptions import BadRequest
from policyengine_api.utils.payload_validators import (
    validate_country,
    validate_tracer_analysis_payload,
)
from policyengine_api.services.tracer_analysis_service import (
    TracerAnalysisService,
)
import json
from policyengine_api.country import COUNTRY_PACKAGE_VERSIONS
import re

tracer_analysis_bp = Blueprint("tracer_analysis", __name__)
tracer_analysis_service = TracerAnalysisService()


@tracer_analysis_bp.route("/<country_id>/tracer-analysis", methods=["POST"])
@validate_country
def execute_tracer_analysis(country_id):

    payload = request.json

    is_payload_valid, message = validate_tracer_analysis_payload(payload)
    if not is_payload_valid:
        raise BadRequest(f"Invalid JSON data; details: {message}")

    household_id = payload.get("household_id")
    policy_id = payload.get("policy_id")
    variable = payload.get("variable")
    api_version = COUNTRY_PACKAGE_VERSIONS[country_id]

    if not isinstance(variable, str):
        raise BadRequest("variable must be a string")

    analysis, analysis_type = tracer_analysis_service.execute_analysis(
        country_id,
        household_id,
        policy_id,
        variable,
    )

    if analysis_type == "static":
        return Response(
            json.dumps({"status": "ok", "result": analysis, "message": None}),
            status=200,
            mimetype="application/json",
        )

    # Create streaming response
    response = Response(
        stream_with_context(analysis),
        status=200,
        mimetype="application/x-ndjson",
    )

    # Set header to prevent buffering on Google App Engine deployment
    # (see https://cloud.google.com/appengine/docs/flexible/how-requests-are-handled?tab=python#x-accel-buffering)
    response.headers["X-Accel-Buffering"] = "no"

    return response
