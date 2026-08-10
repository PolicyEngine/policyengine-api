import json
import logging

from flask import Blueprint, Response, request
from policyengine_core.errors import SituationParsingError
from werkzeug.exceptions import BadRequest, NotFound

from policyengine_api.data.v1_models import Household
from policyengine_api.extensions import cache
from policyengine_api.response_factory import _make_error_response
from policyengine_api.services.household_calculation_service import (
    HouseholdCalculationService,
    HouseholdNotFoundError,
    InvalidHouseholdInputsError,
    PolicyNotFoundError,
)
from policyengine_api.services.household_service import HouseholdService
from policyengine_api.utils import make_cache_key
from policyengine_api.utils.input_validation import format_unrecognized_inputs_message
from policyengine_api.utils.payload_validators import (
    validate_country,
    validate_household_payload,
)

household_bp = Blueprint("household", __name__)
household_service = HouseholdService()
household_calculation_service = HouseholdCalculationService()


def _serialize_household(household: Household) -> dict:
    return {
        "id": household.id,
        "country_id": household.country_id,
        "label": household.label,
        "api_version": household.api_version,
        "household_json": household.household_json,
        "household_hash": household.household_hash,
    }


@household_bp.route("/<country_id>/household/<int:household_id>", methods=["GET"])
@validate_country
def get_household(country_id: str, household_id: int) -> Response:
    """
    Get a household's input data with a given ID.

    Args:
        country_id (str): The country ID.
        household_id (int): The household ID.
    """
    print(f"Got request for household {household_id} in country {country_id}")

    household = household_service.get_household(country_id, household_id)
    result = None if household is None else _serialize_household(household)
    if result is None:
        raise NotFound(f"Household #{household_id} not found.")
    else:
        return Response(
            json.dumps(
                {
                    "status": "ok",
                    "message": None,
                    "result": result,
                }
            ),
            status=200,
            mimetype="application/json",
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
        raise BadRequest(f"Unable to create new household; details: {message}")

    # The household label appears to be unimplemented at this time,
    # thus it should always be 'None'
    label: str | None = payload.get("label")
    household_json: dict = payload.get("data")

    household = household_service.create_household(
        country_id,
        household_json,
        label,
    )
    household_id = household.id

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


@household_bp.route("/<country_id>/household/<int:household_id>", methods=["PUT"])
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
        raise BadRequest(
            f"Unable to update household #{household_id}; details: {message}"
        )

    # First, attempt to fetch the existing household
    label: str | None = payload.get("label")
    household_json: dict = payload.get("data")

    try:
        updated_household = household_service.update_household(
            country_id,
            household_id,
            household_json,
            label,
        )
    except LookupError:
        raise NotFound(f"Household #{household_id} not found.") from None
    updated_household_json = updated_household.household_json
    return Response(
        json.dumps(
            {
                "status": "ok",
                "message": None,
                "result": {
                    "household_id": household_id,
                    "household_json": updated_household_json,
                },
            }
        ),
        status=200,
        mimetype="application/json",
    )


@household_bp.route(
    "/<country_id>/household/<household_id>/policy/<policy_id>",
    methods=["GET"],
)
@validate_country
def get_household_under_policy(country_id: str, household_id: str, policy_id: str):
    """Get a stored household's output under a stored policy."""
    try:
        calculation = household_calculation_service.calculate_stored_household(
            country_id,
            int(household_id),
            int(policy_id),
        )
    except HouseholdNotFoundError:
        return _make_error_response(
            f"Household #{household_id} not found.",
            404,
        )
    except PolicyNotFoundError:
        return _make_error_response(
            f"Policy #{policy_id} not found.",
            404,
        )
    except InvalidHouseholdInputsError as error:
        return _make_error_response(
            format_unrecognized_inputs_message(error.invalid_inputs),
            400,
            result=None,
            errors=[invalid_input.to_dict() for invalid_input in error.invalid_inputs],
        )
    except Exception as error:
        logging.exception(error)
        return _make_error_response(
            f"Error calculating household #{household_id} under policy "
            f"#{policy_id}: {error}",
            500,
        )

    response_body = dict(status="ok", message=None, result=calculation.household)
    if calculation.warnings:
        response_body["warnings"] = list(calculation.warnings)
    return response_body


def _calculate(country_id: str, *, add_missing: bool) -> dict | Response:
    payload = request.json
    household_json = payload.get("household", {})
    policy_json = payload.get("policy", {})

    try:
        calculation = household_calculation_service.calculate_household(
            country_id,
            household_json,
            policy_json,
            add_missing=add_missing,
        )
    except InvalidHouseholdInputsError as error:
        return _make_error_response(
            format_unrecognized_inputs_message(error.invalid_inputs),
            400,
            result=None,
            errors=[invalid_input.to_dict() for invalid_input in error.invalid_inputs],
        )
    except SituationParsingError as error:
        return _make_error_response(
            f"Invalid household payload: {error}",
            400,
            result=None,
        )
    except Exception as error:
        logging.exception(error)
        return _make_error_response(
            f"Error calculating household under policy: {error}",
            500,
        )

    response_body = dict(status="ok", message=None, result=calculation.household)
    if calculation.warnings:
        response_body["warnings"] = list(calculation.warnings)
    return response_body


@household_bp.route("/<country_id>/calculate", methods=["POST"])
@cache.cached(make_cache_key=make_cache_key)
@validate_country
def get_calculate(country_id: str) -> dict | Response:
    """Calculate a household without adding omitted yearly variables."""
    return _calculate(country_id, add_missing=False)


@household_bp.route("/<country_id>/calculate-full", methods=["POST"])
@cache.cached(make_cache_key=make_cache_key)
@validate_country
def get_calculate_full(country_id: str) -> dict | Response:
    """Calculate a household after adding omitted yearly variables."""
    return _calculate(country_id, add_missing=True)
