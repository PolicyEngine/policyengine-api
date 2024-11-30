from flask import Blueprint, Response, request
import json

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.services.household_service import HouseholdService
from policyengine_api.utils import hash_object
from policyengine_api.utils.payload_validators import (
  validate_post_household_payload,
  validate_country
)


household_bp = Blueprint("household", __name__)
household_service = HouseholdService()


@validate_country
@household_bp.route("/<country_id>/household/<household_id>", methods=["GET"])
def get_household(country_id: str, household_id: str) -> dict:
    """
    Get a household's input data with a given ID.

    Args:
        country_id (str): The country ID.
        household_id (str): The household ID.
    """

    # Ensure that household ID is a number
    try:
        household_id = int(household_id)
    except ValueError:
        return Response(
            status=400, response=f"Invalid household ID; household ID must be a number"
        )

    try:
        household: dict | None = household_service.get_household(country_id, household_id)
        if household is None:
            return Response(
                json.dumps(
                   {
                        "status": "error",
                        "message": f"Household #{household_id} not found.",
                    }
                ),
                status=404
            )
        else:
            return Response(
                json.dumps(
                    {
                        "status": "ok",
                        "message": None,
                        "result": household,
                    }
                ), status=200
            )
    except Exception as e:
        return Response(
            json.dumps(
                {
                    "status": "error",
                    "message": f"An error occurred while fetching household #{household_id}. Details: {str(e)}",
                }
            ),
            status=500
        )

@validate_country
@household_bp.route("/<country_id>/household", methods=["POST"])
def post_household(country_id: str) -> dict:
    """
    Set a household's input data.

    Args:
        country_id (str): The country ID.
    """

    # Validate payload
    payload = request.json
    is_payload_valid, message = validate_post_household_payload(payload)
    if not is_payload_valid:
        return Response(
            status=400,
            response=f"Unable to create new household; details: {message}",
        )
    
    try:
        # The household label appears to be unimplemented at this time,
        # thus it should always be 'None'
        label: str | None = payload.get("label")
        household_json: dict = payload.get("data")
        household_hash: str = hash_object(household_json)
        api_version: str = COUNTRY_PACKAGE_VERSIONS.get(country_id)

        household_id = household_service.create_household(
            country_id, household_json, household_hash, label, api_version
        )

        return Response(
            json.dumps(
                {
                    "status": "ok",
                    "message": None,
                    "result": {
                        "household_id": household_id,
                    }
                }
            ), 
            status=201,
            mimetype="application/json"
        )

    except Exception as e:
        return Response(
            json.dumps(
                {
                    "status": "error",
                    "message": f"An error occurred while creating a new household. Details: {str(e)}",
                }
            ),
            status=500,
            mimetype="application/json"
        )


# app.route("/<country_id>/household/<household_id>", methods=["GET"])(
#     get_household
# )
# 
# app.route("/<country_id>/household", methods=["POST"])(post_household)
# 
# app.route("/<country_id>/household/<household_id>", methods=["PUT"])(
#     update_household
# )