from flask import Blueprint, Response, request
from policyengine_api.services.ai_prompt_service import AIPromptService
from policyengine_api.utils.payload_validators import validate_country
from policyengine_api.utils.payload_validators.ai import (
    validate_sim_analysis_payload,
)
from werkzeug.exceptions import NotFound, BadRequest
import json


ai_prompt_bp = Blueprint("ai_prompt", __name__)
ai_prompt_service = AIPromptService()


@validate_country
@ai_prompt_bp.route(
    "/<country_id>/ai-prompts/<string:prompt_name>",
    methods=["POST"],
)
def generate_ai_prompt(country_id, prompt_name: str) -> Response:
    """
    Get an AI prompt with a given name, filled with the given data.
    """
    print(f"Got request for AI prompt {prompt_name}")

    payload = request.json

    is_payload_valid, message = validate_sim_analysis_payload(payload)
    if not is_payload_valid:
        raise BadRequest(f"Invalid JSON data; details: {message}")

    input_data = {
        "country_id": country_id,
    }
    for key in payload:
        input_data[key] = payload.get(key)

    prompt: str | None = ai_prompt_service.get_prompt(
        name=prompt_name, input_data=input_data
    )
    if prompt is None:
        raise NotFound(f"Prompt with name {prompt_name} not found.")

    return Response(
        json.dumps(
            {
                "status": "ok",
                "message": None,
                "result": prompt,
            }
        ),
        status=200,
        mimetype="application/json",
    )
