"""Flask routes for v1 households and calculations, with optional copying to API v2."""

import contextlib
import json
import logging
import time
from collections.abc import Callable
from functools import wraps
from http import HTTPStatus
from typing import TypeVar

from flask import Blueprint, Response, g, request
from policyengine_core.errors import SituationParsingError
from werkzeug.exceptions import BadRequest, NotFound

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS, POLICYENGINE_VERSION
from policyengine_api.data.v1_models import Household
from policyengine_api.data.v2.catalog.catalog_selection import SUPPORTED_V2_COUNTRY_IDS
from policyengine_api.extensions import cache
from policyengine_api.gcp_logging import logger
from policyengine_api.migration_flags import (
    get_v1_household_read_source,
    get_v1_household_write_source,
)
from policyengine_api.request_context import (
    current_request_id,
    start_observability_id,
)
from policyengine_api.response_factory import _make_error_response
from policyengine_api.services.household_calculation_service import (
    HouseholdCalculationOptions,
    HouseholdCalculationResult,
    HouseholdCalculationService,
    HouseholdNotFoundError,
    InvalidHouseholdInputsError,
    PolicyNotFoundError,
)
from policyengine_api.services.household_mirroring import (
    HouseholdMirrorUnavailableError,
    process_household_event_after_commit,
)
from policyengine_api.services.household_service import (
    HouseholdCreateResult,
    HouseholdPersistenceError,
    HouseholdService,
)
from policyengine_api.spm import (
    SPMValidationError,
    normalize_spm_selection,
    spm_error_detail,
)
from policyengine_api.utils import hash_object
from policyengine_api.utils.input_validation import format_invalid_inputs_message
from policyengine_api.utils.payload_validators import (
    validate_country,
    validate_household_payload,
)

_ViewResult = TypeVar("_ViewResult")

# Standard-library logger for tracebacks; ``logger`` is the structured
# log_struct facade.
module_logger = logging.getLogger(__name__)

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


def _copy_household_to_v2(
    country_id: str,
    household_id: int,
    creation: HouseholdCreateResult,
) -> None:
    """Copy a committed v1 household into v2 without changing the v1 response.

    A failed copy leaves the create event pending for the event-processing
    workflow (`process-v1-household-mirror-event.yml`).
    """
    if creation.mirror_event_id is None or creation.snapshot is None:
        # A logging failure must not replace the committed v1 response.
        with contextlib.suppress(Exception):
            logger.log_struct(
                {
                    "message": "V1 household committed without a v2 copy",
                    "metric_name": "v1_household_mirror_operations",
                    "metric_value": 1,
                    "configured_write_source": "dual_write",
                    "attempted_write_sources": ["cloud_sql", "supabase"],
                    "actual_write_sources": ["cloud_sql"],
                    "country_id": country_id,
                    "legacy_household_id": household_id,
                    "outcome": "error",
                    "failure_category": "missing_mirror_event",
                },
                severity="ERROR",
            )
        return
    # process_household_event_after_commit has already logged the failure and
    # its category, and the create event stays pending.
    with contextlib.suppress(HouseholdMirrorUnavailableError):
        process_household_event_after_commit(
            country_id,
            household_id,
            event_service=household_service,
        )


def _household_persistence_failure(
    error: HouseholdPersistenceError,
    *,
    country_id: str,
    configured_write_source: str,
    started_at: float,
) -> Response:
    status_code = 503 if error.retryable else 500
    # Metric logging must not replace the error response.
    with contextlib.suppress(Exception):
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
    message = (
        "Household database is temporarily unavailable; please try again later."
        if status_code == HTTPStatus.SERVICE_UNAVAILABLE
        else "Internal database error; please try again later."
    )
    return _make_error_response(message, status_code)


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


def _invalid_household_inputs_response(error: InvalidHouseholdInputsError) -> Response:
    """Return the 400 that lists every invalid calculation input."""
    return _make_error_response(
        format_invalid_inputs_message(error.invalid_inputs),
        400,
        result=None,
        errors=[invalid_input.to_dict() for invalid_input in error.invalid_inputs],
    )


def _calculation_response(calculation: HouseholdCalculationResult) -> dict:
    result: dict[str, object] = {
        "status": "ok",
        "message": None,
        "result": calculation.household,
    }
    if calculation.warnings:
        result["warnings"] = list(calculation.warnings)
    if calculation.spm_provenance is not None:
        result["spm_provenance"] = calculation.spm_provenance
    return result


def _requested_spm(country_id: str, payload: dict) -> object:
    """Read a chosen selection, treating an explicit null as a malformed one.

    A v2 document and a simulation record both refuse an explicit null rather
    than reading it as "no choice". v1 must not be the one surface where null
    quietly inherits the certified defaults, because omission and choice no
    longer mean the same thing for storage or for replay.

    A country without SPM settings reports the field itself as unsupported,
    exactly as a non-null selection does there, rather than inviting the caller
    to correct the shape of a field it would reject whatever shape it had.
    """
    if "spm" not in payload:
        return None
    selection = payload["spm"]
    if country_id != "us":
        error_code = "SPM_SETTINGS_UNSUPPORTED"
        raise SPMValidationError(
            error_code, "SPM settings are only available for the US"
        )
    if selection is None:
        error_code = "SPM_SETTINGS_INVALID"
        raise SPMValidationError(
            error_code,
            "spm must be an object; omit it to inherit the certified defaults.",
        )
    return selection


def _validate_calculation_request(
    *, add_missing: bool
) -> Callable[
    [Callable[..., _ViewResult]],
    Callable[..., _ViewResult | Response],
]:
    """Validate calculation inputs before an HTTP cache can satisfy a request."""

    def decorator(
        func: Callable[..., _ViewResult],
    ) -> Callable[..., _ViewResult | Response]:
        @wraps(func)
        def wrapped(
            country_id: str, *args: object, **kwargs: object
        ) -> _ViewResult | Response:
            payload = request.get_json()
            if not isinstance(payload, dict):
                msg = "Calculation payload must be a JSON object."
                raise BadRequest(msg)
            try:
                selection = _requested_spm(country_id, payload)
                g.spm_requested = selection is not None
                g.spm = normalize_spm_selection(country_id, selection)
                g.prepared_household_calculation = (
                    household_calculation_service.prepare_household_calculation(
                        country_id,
                        payload.get("household", {}),
                        payload.get("policy", {}),
                        options=HouseholdCalculationOptions(
                            add_missing=add_missing,
                            **(
                                {
                                    "spm": g.spm,
                                    "spm_requested": g.spm_requested,
                                }
                                if g.spm is not None
                                else {}
                            ),
                        ),
                    )
                )
            except InvalidHouseholdInputsError as error:
                return _invalid_household_inputs_response(error)
            except ValueError as error:
                response = _spm_error_response(error)
                if response is not None:
                    return response
                raise
            result = func(country_id, *args, **kwargs)
            if not g.get("calculation_view_executed", False) and (
                not isinstance(result, Response)
                or result.status_code < HTTPStatus.BAD_REQUEST
            ):
                start_observability_id()
            return result

        return wrapped

    return decorator


def _calculation_cache_key(*_args: object, **_kwargs: object) -> str:
    country_id = request.view_args["country_id"]
    return hash_object(
        {
            "schema": 3,
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
    """Get a household's input data with a given ID.

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
        msg = f"Household #{household_id} not found."
        raise NotFound(msg)
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
    """Set a household's input data.

    Args:
        country_id (str): The country ID.

    """
    # Validate payload
    payload = request.json
    is_payload_valid, message = validate_household_payload(payload)
    if not is_payload_valid:
        msg = f"Unable to create new household; details: {message}"
        raise BadRequest(msg)

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
        selection = _requested_spm(country_id, payload)
        creation = household_service.create_household(
            country_id,
            household_json,
            label,
            record_mirror_event=copy_to_v2,
            **({"spm": selection} if selection is not None else {}),
        )
    except HouseholdPersistenceError as error:
        return _household_persistence_failure(
            error,
            country_id=country_id,
            configured_write_source=write_source,
            started_at=persistence_started_at,
        )
    except ValueError as error:
        response = _spm_error_response(error)
        if response is not None:
            return response
        raise
    household_id = creation.household.id

    if copy_to_v2:
        _copy_household_to_v2(country_id, household_id, creation)

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
def get_household_under_policy(
    country_id: str, household_id: str, policy_id: str
) -> dict | Response:
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
            on_accepted=start_observability_id,
        )
    except (
        HouseholdNotFoundError,
        PolicyNotFoundError,
        InvalidHouseholdInputsError,
    ) as error:
        return _stored_calculation_error_response(
            error,
            household_id=household_id,
            policy_id=policy_id,
        )
    except Exception as error:
        response = _spm_error_response(error)
        if response is not None:
            return response
        module_logger.exception(
            "Error calculating household #%s under policy #%s",
            household_id,
            policy_id,
        )
        return _make_error_response(
            f"Error calculating household #{household_id} under policy "
            f"#{policy_id}: {error}",
            500,
        )

    return _calculation_response(calculation)


def _stored_calculation_error_response(
    error: HouseholdNotFoundError | PolicyNotFoundError | InvalidHouseholdInputsError,
    *,
    household_id: str,
    policy_id: str,
) -> Response:
    """Map an expected stored-household calculation failure to its error response."""
    if isinstance(error, HouseholdNotFoundError):
        return _make_error_response(
            f"Household #{household_id} not found.",
            404,
        )
    if isinstance(error, PolicyNotFoundError):
        return _make_error_response(
            f"Policy #{policy_id} not found.",
            404,
        )
    return _invalid_household_inputs_response(error)


def _calculate() -> dict | Response:
    g.calculation_view_executed = True
    parse_failure = _parse_prepared_household_calculation()
    if parse_failure is not None:
        return parse_failure

    try:
        calculation = household_calculation_service.calculate_prepared_household(
            g.prepared_household_calculation,
        )
    except (InvalidHouseholdInputsError, SituationParsingError) as error:
        return _calculation_error_response(error)
    except Exception as error:
        response = _spm_error_response(error)
        if response is not None:
            return response
        module_logger.exception("Error calculating household under policy")
        return _make_error_response(
            f"Error calculating household under policy: {error}",
            500,
        )

    return _calculation_response(calculation)


def _parse_prepared_household_calculation() -> Response | None:
    """Parse the validated request's household, or return its error response.

    An unexpected failure starts the request's observability ID and logs its
    traceback.
    """
    try:
        g.prepared_household_calculation = (
            household_calculation_service.parse_prepared_household(
                g.prepared_household_calculation,
                on_accepted=start_observability_id,
            )
        )
    except SituationParsingError as error:
        return _make_error_response(
            f"Invalid household payload: {error}",
            400,
            result=None,
        )
    except Exception as error:
        response = _spm_error_response(error)
        if response is not None:
            return response
        start_observability_id()
        module_logger.exception("Error calculating household under policy")
        return _make_error_response(
            f"Error calculating household under policy: {error}",
            500,
        )
    return None


def _calculation_error_response(
    error: InvalidHouseholdInputsError | SituationParsingError,
) -> Response:
    """Map an expected household calculation failure to its error response."""
    if isinstance(error, InvalidHouseholdInputsError):
        return _invalid_household_inputs_response(error)
    response = _spm_error_response(error)
    if response is not None:
        return response
    return _make_error_response(
        f"Invalid household payload: {error}",
        400,
        result=None,
    )


@household_bp.route("/<country_id>/calculate", methods=["POST"])
@validate_country
@_validate_calculation_request(add_missing=False)
@cache.cached(make_cache_key=_calculation_cache_key)
def get_calculate(country_id: str) -> dict | Response:  # noqa: ARG001  # Flask passes the <country_id> URL variable by keyword
    """Calculate a household without adding omitted yearly variables."""
    return _calculate()


@household_bp.route("/<country_id>/calculate-full", methods=["POST"])
@validate_country
@_validate_calculation_request(add_missing=True)
@cache.cached(make_cache_key=_calculation_cache_key)
def get_calculate_full(country_id: str) -> dict | Response:  # noqa: ARG001  # Flask passes the <country_id> URL variable by keyword
    """Calculate a household after adding omitted yearly variables."""
    return _calculate()
