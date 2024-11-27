from flask import Blueprint, Response, request
import json

from policyengine_api.services.policy_service import PolicyService
from policyengine_api.utils.payload_validators import (
    validate_country,
    validate_set_policy_payload,
)

policy_bp = Blueprint("policy", __name__)
policy_service = PolicyService()


@policy_bp.route("/<policy_id>", methods=["GET"])
@validate_country
def get_policy(country_id: str, policy_id: int | str) -> Response:
    """
    Get policy data for a given country and policy ID.

    Args:
        country_id (str): The
        policy_id (int | str): The policy ID.

    Returns:
        Response: A Flask response object containing the
        policy data in JSON format
    """

    if policy_id is None:
        return Response(
            json.dumps(
                {"status": "error", "message": "Policy ID not provided."},
                status=400,
            )
        )

    try:
        # Specifically cast policy_id to an integer
        policy_id = int(policy_id)

        policy: dict | None = policy_service.get_policy(country_id, policy_id)
        print(policy)
        print(type(policy))
        print(type(policy["policy_json"]))

        if policy is None:
            return Response(
                json.dumps(
                    {
                        "status": "error",
                        "message": f"Policy #{policy_id} not found",
                    }
                ),
                status=404,
            )
        else:
            return Response(
                json.dumps(
                    {"status": "ok", "message": None, "result": policy}
                ),
                status=200,
            )

    except Exception as e:
        return Response(
            json.dumps(
                {
                    "status": "error",
                    "message": f"An error occurred while fetching policy data: {str(e)}",
                },
                status=500,
            )
        )


@policy_bp.route("", methods=["POST"])
@validate_country
def set_policy(country_id: str) -> Response:
    """
    Set policy data for a given country and policy. If the policy already exists,
    fail quietly by returning a 200, but passing a warning message and the previously
    created policy

    Args:
        country_id (str): The country ID.
    """

    payload = request.json

    is_payload_valid, message = validate_set_policy_payload(payload)
    if not is_payload_valid:
        return Response(
            status=400, response=f"Invalid JSON data; details: {message}"
        )

    label = payload.pop("label", None)
    policy_json = payload.pop("data", None)

    try:
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
        return Response(
            json.dumps(response_body), status=code, mimetype="application/json"
        )

    except Exception as e:
        return Response(
            json.dumps(
                {
                    "status": "error",
                    "message": f"An error occurred while setting policy data: {str(e)}",
                },
                status=500,
            )
        )
