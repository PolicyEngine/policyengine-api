from flask import Blueprint, Response
import json
from policyengine_api.utils.payload_validators import validate_country
from policyengine_api.services.household_service import HouseholdService


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



# app.route("/<country_id>/household/<household_id>", methods=["GET"])(
#     get_household
# )
# 
# app.route("/<country_id>/household", methods=["POST"])(post_household)
# 
# app.route("/<country_id>/household/<household_id>", methods=["PUT"])(
#     update_household
# )