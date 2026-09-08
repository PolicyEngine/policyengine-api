import json
import logging
import time

from flask import Blueprint, Response, request
from policyengine_core.errors import SituationParsingError
from werkzeug.exceptions import BadRequest, NotFound

from policyengine_api.data.v1_models import Household
from policyengine_api.data.v2.catalog.catalog_selection import SUPPORTED_V2_COUNTRY_IDS
from policyengine_api.extensions import cache
from policyengine_api.gcp_logging import logger
from policyengine_api.migration_flags import (
    get_v1_household_read_source,
    get_v1_household_write_source,
)
from policyengine_api.request_context import current_request_id
from policyengine_api.response_factory import _make_error_response
from policyengine_api.services.household_mirroring import (
    HouseholdMirrorUnavailableError,
    process_household_event_after_commit,
)
from policyengine_api.services.household_calculation_service import (
    HouseholdCalculationService,
    HouseholdNotFoundError,
    InvalidHouseholdInputsError,
    PolicyNotFoundError,
)
from policyengine_api.services.household_service import (
    HouseholdPersistenceError,
    HouseholdService,
)
from policyengine_api.utils import make_cache_key
from policyengine_api.utils.input_validation import format_unrecognized_inputs_message
from policyengine_api.utils.payload_validators import (
    validate_country,
    validate_household_payload,
)

household_bp = Blueprint("household", __name__)
household_service = HouseholdService()
household_calculation_service = HouseholdCalculationService()


def _should_copy_to_v2(country_id: str, write_source: str) -> bool:
    return write_source == "dual_write" and country_id in SUPPORTED_V2_COUNTRY_IDS


def _household_configuration_unavailable() -> Response:
    return _make_error_response(
        "Household persistence configuration is unavailable.",
        503,
    )


def _household_copy_unavailable() -> Response:
    return _make_error_response(
        "The v1 household was committed, but its retained create event has not "
        "been copied to v2.",
        503,
    )


def _household_persistence_failure(
    error: HouseholdPersistenceError,
    *,
    country_id: str,
    configured_write_source: str,
    started_at: float,
) -> Response:
    status_code = 503 if error.retryable else 500
    try:
        logger.log_struct(
            {
                "message": "V1 household persistence failed",
                "metric_name": "v1_household_persistence_failures",
                "metric_value": 1,
                "resource": "household",
                "operation": "create",
                "database_source": "cloud_sql",
                "configured_write_source": configured_write_source,
                "country_id": country_id,
                "request_id": current_request_id(),
                "outcome": "error",
                "failure_category": error.category.value,
                "http_status": status_code,
                "duration_ms": round((time.perf_counter() - started_at) * 1000, 3),
            },
            severity="ERROR",
        )
    except Exception:
        pass
    message = (
        "Household database is temporarily unavailable; please try again later."
        if status_code == 503
        else "Internal database error; please try again later."
    )
    return _make_error_response(message, status_code)


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
    try:
        get_v1_household_read_source()
    except ValueError:
        return _household_configuration_unavailable()

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
        write_source = get_v1_household_write_source()
        get_v1_household_read_source()
    except ValueError:
        return _household_configuration_unavailable()
    copy_to_v2 = _should_copy_to_v2(country_id, write_source)
    persistence_started_at = time.perf_counter()
    try:
        creation = household_service.create_household(
            country_id,
            household_json,
            label,
            record_mirror_event=copy_to_v2,
        )
    except HouseholdPersistenceError as error:
        return _household_persistence_failure(
            error,
            country_id=country_id,
            configured_write_source=write_source,
            started_at=persistence_started_at,
        )
    household_id = creation.household.id

    if copy_to_v2:
        if creation.mirror_event_id is None or creation.snapshot is None:
            return _household_copy_unavailable()
        try:
            process_household_event_after_commit(
                country_id,
                household_id,
                event_service=household_service,
            )
        except HouseholdMirrorUnavailableError:
            return _household_copy_unavailable()

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


@household_bp.route(
    "/<country_id>/household/<household_id>/policy/<policy_id>",
    methods=["GET"],
)
@validate_country
def get_household_under_policy(country_id: str, household_id: str, policy_id: str):
    """Get a stored household's output under a stored policy."""
    try:
        get_v1_household_read_source()
    except ValueError:
        return _household_configuration_unavailable()
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
