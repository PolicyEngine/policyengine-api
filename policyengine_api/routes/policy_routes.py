from flask import Blueprint, Response
import json

from policyengine_api.services.policy_service import PolicyService
from policyengine_api.utils.payload_validators import validate_country

policy_bp = Blueprint("policy", __name__)
policy_service = PolicyService()

@policy_bp.route("/<policy_id>", methods=["GET"])
@validate_country
def get_country(country_id: str, policy_id: int | str) -> Response:
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
            json.dumps({
                "status": "error",
                "message": "Policy ID not provided."
            },
            status=400)
        )

    try:
      # Specifically cast policy_id to an integer
      policy_id = int(policy_id)

      policy: dict | None = policy_service.get_policy(country_id, policy_id)

      if policy is None:
          return Response(
              json.dumps({
                  "status": "error",
                  "message": f"Policy #{policy_id} not found"
              }),
              status=404
          )
      else:
          return Response(
              json.dumps({
                  "status": "ok",
                  "message": None,
                  "result": policy
              }),
              status=200
          )



    except Exception as e:
        return Response(
            json.dumps({
                "status": "error",
                "message": f"An error occurred while fetching policy data: {str(e)}"
            },
            status=500)
        )
