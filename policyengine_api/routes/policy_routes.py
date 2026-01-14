from flask import Blueprint, Response, request
import json

from policyengine_api.services.policy_service import PolicyService
from werkzeug.exceptions import NotFound, BadRequest
from policyengine_api.utils.payload_validators import (
    validate_country,
    validate_set_policy_payload,
)

policy_bp = Blueprint("policy", __name__)
policy_service = PolicyService()


@policy_bp.route("/<country_id>/policy/<int:policy_id>", methods=["GET"])
@validate_country
def get_policy(country_id: str, policy_id: int | str) -> Response:
    """
    Get policy data for a given country and policy ID.

    Args:
        country_id (str)
        policy_id (int | str)

    Returns:
        Response: A Flask response object containing the
        policy data in JSON format
    """

    # Specifically cast policy_id to an integer
    policy_id = int(policy_id)

    policy: dict | None = policy_service.get_policy(country_id, policy_id)

    if policy is None:
        raise NotFound(f"Policy #{policy_id} not found.")

    return Response(
        json.dumps({"status": "ok", "message": None, "result": policy}),
        status=200,
    )


@policy_bp.route("/<country_id>/policy", methods=["POST"])
@validate_country
def set_policy(country_id: str) -> Response:
    """
    Set policy data for given country and policy. If policy already exists,
    return existing policy and 200.

    Args:
        country_id (str)
    """

    payload = request.json

    is_payload_valid, message = validate_set_policy_payload(payload)
    if not is_payload_valid:
        raise BadRequest(f"Invalid JSON data; details: {message}")

    label = payload.pop("label", None)
    policy_json = payload.pop("data", None)

    policy_id, message, is_existing_policy = policy_service.set_policy(
        country_id,
        label,
        policy_json,
    )

    response_body = dict(
        status="ok",
        message=message,
        result=dict(
            policy_id=policy_id,
        ),
    )

    code = 200 if is_existing_policy else 201
    return Response(json.dumps(response_body), status=code, mimetype="application/json")
