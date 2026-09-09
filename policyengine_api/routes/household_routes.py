import json
import logging
from functools import wraps

from flask import Blueprint, Response, g, request
from policyengine_core.errors import SituationParsingError
from werkzeug.exceptions import BadRequest, NotFound

from policyengine_api.data.v1_models import Household
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS, POLICYENGINE_VERSION
from policyengine_api.extensions import cache
from policyengine_api.response_factory import _make_error_response
from policyengine_api.services.household_calculation_service import (
    HouseholdCalculationService,
    HouseholdNotFoundError,
    InvalidHouseholdInputsError,
    PolicyNotFoundError,
)
from policyengine_api.services.household_service import HouseholdService
from policyengine_api.spm import normalize_spm_selection, spm_error_detail
from policyengine_api.utils import hash_object
from policyengine_api.utils.input_validation import format_unrecognized_inputs_message
from policyengine_api.utils.payload_validators import (
    validate_country,
    validate_household_payload,
)

household_bp = Blueprint("household", __name__)
household_service = HouseholdService()
household_calculation_service = HouseholdCalculationService()


def _serialize_household(household: Household) -> dict:
    inputs = dict(household.household_json)
    spm = inputs.pop("spm", None)
    result = {
        "id": household.id,
        "country_id": household.country_id,
        "label": household.label,
        "api_version": household.api_version,
        "household_json": inputs,
        "household_hash": household.household_hash,
    }
    if spm is not None:
        result["spm"] = spm
    return result


def _spm_error_response(error: Exception) -> Response | None:
    detail = spm_error_detail(error)
    if detail is not None:
        return _make_error_response(
            detail["message"], 400, result=None, errors=[detail]
        )
    return None


def _calculation_response(calculation) -> dict:
    result = dict(status="ok", message=None, result=calculation.household)
    if calculation.warnings:
        result["warnings"] = list(calculation.warnings)
    for field in ("spm_config", "spm_provenance"):
        value = getattr(calculation, field, None)
        if value is not None:
            result[field] = value
    return result


def _validate_calculation_spm(func):
    """Validate current certification before an HTTP cache can satisfy a request."""

    @wraps(func)
    def wrapped(country_id, *args, **kwargs):
        payload = request.get_json()
        if not isinstance(payload, dict):
            raise BadRequest("Calculation payload must be a JSON object.")
        try:
            g.spm = normalize_spm_selection(country_id, payload.get("spm"))
        except ValueError as error:
            response = _spm_error_response(error)
            if response is not None:
                return response
            raise
        return func(country_id, *args, **kwargs)

    return wrapped


def _calculation_cache_key(*args, **kwargs):
    country_id = request.view_args["country_id"]
    return hash_object(
        {
            "schema": 2,
            "path": request.full_path,
            "payload": request.get_json(),
            "spm": g.spm,
            "country_version": COUNTRY_PACKAGE_VERSIONS[country_id],
            "policyengine_version": POLICYENGINE_VERSION,
        }
    )


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

    try:
        household = household_service.create_household(
            country_id,
            household_json,
            label,
            **({"spm": payload["spm"]} if "spm" in payload else {}),
        )
    except ValueError as error:
        response = _spm_error_response(error)
        if response is not None:
            return response
        raise
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
            **({"spm": payload["spm"]} if "spm" in payload else {}),
        )
    except LookupError:
        raise NotFound(f"Household #{household_id} not found.") from None
    except ValueError as error:
        response = _spm_error_response(error)
        if response is not None:
            return response
        raise
    serialized = _serialize_household(updated_household)
    return Response(
        json.dumps(
            {
                "status": "ok",
                "message": None,
                "result": {
                    "household_id": household_id,
                    "household_json": serialized["household_json"],
                    **({"spm": serialized["spm"]} if "spm" in serialized else {}),
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
        response = _spm_error_response(error)
        if response is not None:
            return response
        logging.exception(error)
        return _make_error_response(
            f"Error calculating household #{household_id} under policy "
            f"#{policy_id}: {error}",
            500,
        )

    return _calculation_response(calculation)


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
            **({"spm": g.spm} if g.get("spm") is not None else {}),
        )
    except InvalidHouseholdInputsError as error:
        return _make_error_response(
            format_unrecognized_inputs_message(error.invalid_inputs),
            400,
            result=None,
            errors=[invalid_input.to_dict() for invalid_input in error.invalid_inputs],
        )
    except SituationParsingError as error:
        response = _spm_error_response(error)
        if response is not None:
            return response
        return _make_error_response(
            f"Invalid household payload: {error}",
            400,
            result=None,
        )
    except Exception as error:
        response = _spm_error_response(error)
        if response is not None:
            return response
        logging.exception(error)
        return _make_error_response(
            f"Error calculating household under policy: {error}",
            500,
        )

    return _calculation_response(calculation)


@household_bp.route("/<country_id>/calculate", methods=["POST"])
@validate_country
@_validate_calculation_spm
@cache.cached(make_cache_key=_calculation_cache_key)
def get_calculate(country_id: str) -> dict | Response:
    """Calculate a household without adding omitted yearly variables."""
    return _calculate(country_id, add_missing=False)


@household_bp.route("/<country_id>/calculate-full", methods=["POST"])
@validate_country
@_validate_calculation_spm
@cache.cached(make_cache_key=_calculation_cache_key)
def get_calculate_full(country_id: str) -> dict | Response:
    """Calculate a household after adding omitted yearly variables."""
    return _calculate(country_id, add_missing=True)
