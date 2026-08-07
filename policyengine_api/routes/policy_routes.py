from flask import Blueprint, Response, request
import json

from policyengine_api.data.orm import get_v1_session_factory
from policyengine_api.data.v1_models import Policy
from policyengine_api.services.policy_service import PolicyService
from werkzeug.exceptions import NotFound, BadRequest
from policyengine_api.utils.payload_validators import (
    validate_country,
    validate_set_policy_payload,
)

policy_bp = Blueprint("policy", __name__)
policy_service = PolicyService()


def _serialize_policy(policy: Policy) -> dict:
    return {
        "id": policy.id,
        "country_id": policy.country_id,
        "label": policy.label,
        "api_version": policy.api_version,
        "policy_json": policy.policy_json,
        "policy_hash": policy.policy_hash,
    }


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

    sessions = get_v1_session_factory()
    with sessions() as session:
        policy = policy_service.get_policy(session, country_id, policy_id)
        result = None if policy is None else _serialize_policy(policy)

    if result is None:
        raise NotFound(f"Policy #{policy_id} not found.")

    return Response(
        json.dumps({"status": "ok", "message": None, "result": result}),
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

    with get_v1_session_factory().begin() as session:
        policy_id, message, is_existing_policy = policy_service.set_policy(
            session,
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
