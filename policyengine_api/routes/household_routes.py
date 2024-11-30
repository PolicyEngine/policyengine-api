from flask import Blueprint, Response, request
import json

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.services.household_service import HouseholdService
from policyengine_api.utils import hash_object
from policyengine_api.utils.payload_validators import (
    validate_household_payload,
    validate_country,
)


household_bp = Blueprint("household", __name__)
household_service = HouseholdService()


@validate_country
@household_bp.route("/<country_id>/household/<household_id>", methods=["GET"])
def get_household(country_id: str, household_id: str) -> Response:
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
            status=400,
            response=f"Invalid household ID; household ID must be a number",
        )

    try:
        household: dict | None = household_service.get_household(
            country_id, household_id
        )
        if household is None:
            return Response(
                json.dumps(
                    {
                        "status": "error",
                        "message": f"Household #{household_id} not found.",
                    }
                ),
                status=404,
            )
        else:
            return Response(
                json.dumps(
                    {
                        "status": "ok",
                        "message": None,
                        "result": household,
                    }
                ),
                status=200,
            )
    except Exception as e:
        return Response(
            json.dumps(
                {
                    "status": "error",
                    "message": f"An error occurred while fetching household #{household_id}. Details: {str(e)}",
                }
            ),
            status=500,
        )


@validate_country
@household_bp.route("/<country_id>/household", methods=["POST"])
def post_household(country_id: str) -> Response:
    """
    Set a household's input data.

    Args:
        country_id (str): The country ID.
    """

    # Validate payload
    payload = request.json
    is_payload_valid, message = validate_household_payload(payload)
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

        household_id = household_service.create_household(
            country_id, household_json, label
        )

        return Response(
            json.dumps(
                {
                    "status": "ok",
                    "message": None,
                    "result": {
                        "household_id": household_id,
                    },
                }
            ),
            status=201,
            mimetype="application/json",
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
            mimetype="application/json",
        )


@validate_country
@household_bp.route("/<country_id>/household/<household_id>", methods=["PUT"])
def update_household(country_id: str, household_id: str) -> Response:
    """
    Update a household's input data.

    Args:
        country_id (str): The country ID.
        household_id (str): The household ID.
    """

    # Validate payload
    payload = request.json
    is_payload_valid, message = validate_household_payload(payload)
    if not is_payload_valid:
        return Response(
            status=400,
            response=f"Unable to update household #{household_id}; details: {message}",
        )

    try:

        # First, attempt to fetch the existing household
        label: str | None = payload.get("label")
        household_json: dict = payload.get("data")

        household: dict | None = household_service.get_household(
            country_id, household_id
        )
        if household is None:
            return Response(
                json.dumps(
                    {
                        "status": "error",
                        "message": f"Household #{household_id} not found.",
                    }
                ),
                status=404,
            )

        # Next, update the household
        household_service.update_household(
            country_id, household_id, household_json, label
        )
        return Response(
            json.dumps(
                {
                    "status": "ok",
                    "message": None,
                    "result": {
                        "household_id": household_id,
                    },
                }
            ),
            status=200,
            mimetype="application/json",
        )
    except Exception as e:
        return Response(
            json.dumps(
                {
                    "status": "error",
                    "message": f"An error occurred while updating household #{household_id}. Details: {str(e)}",
                }
            ),
            status=500,
            mimetype="application/json",
        )
