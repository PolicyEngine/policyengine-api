from flask import Blueprint, Response, request, jsonify
from werkzeug.exceptions import InternalServerError
import json

from policyengine_api.routes.error_routes import response_400, response_404
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.services.household_service import HouseholdService
from policyengine_api.utils import hash_object
from policyengine_api.utils.payload_validators import (
    validate_household_payload,
    validate_country,
)


household_bp = Blueprint("household", __name__)
household_service = HouseholdService()


@household_bp.route(
    "/<country_id>/household/<int:household_id>", methods=["GET"]
)
@validate_country
def get_household(country_id: str, household_id: int) -> Response:
    """
    Get a household's input data with a given ID.

    Args:
        country_id (str): The country ID.
        household_id (int): The household ID.
    """
    print(f"Got request for household {household_id} in country {country_id}")

    try:
        household: dict | None = household_service.get_household(
            country_id, household_id
        )
        if household is None:
            return response_404(f"Household #{household_id} not found.")
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
                mimetype="application/json",
            )
    except Exception as e:
        raise InternalServerError(
            f"An error occurred while fetching household #{household_id}. Details: {str(e)}"
        )


@household_bp.route("/<country_id>/household", methods=["POST"])
@validate_country
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
        return response_400(
            f"Unable to create new household; details: {message}"
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
        raise InternalServerError(
            f"An error occurred while creating a new household. Details: {str(e)}"
        )


@household_bp.route(
    "/<country_id>/household/<int:household_id>", methods=["PUT"]
)
@validate_country
def update_household(country_id: str, household_id: int) -> Response:
    """
    Update a household's input data.

    Args:
        country_id (str): The country ID.
        household_id (int): The household ID.
    """

    # Validate payload
    payload = request.json
    is_payload_valid, message = validate_household_payload(payload)
    if not is_payload_valid:
        return response_400(
            f"Unable to update household #{household_id}; details: {message}"
        )

    try:

        # First, attempt to fetch the existing household
        label: str | None = payload.get("label")
        household_json: dict = payload.get("data")

        household: dict | None = household_service.get_household(
            country_id, household_id
        )
        if household is None:
            return response_404(f"Household #{household_id} not found.")

        # Next, update the household
        updated_household: dict = household_service.update_household(
            country_id, household_id, household_json, label
        )
        return Response(
            json.dumps(
                {
                    "status": "ok",
                    "message": None,
                    "result": {
                        "household_id": household_id,
                        "household_json": updated_household["household_json"],
                    },
                }
            ),
            status=200,
            mimetype="application/json",
        )
    except Exception as e:
        raise InternalServerError(
            f"An error occurred while updating household #{household_id}. Details: {str(e)}"
        )
