"""HTTP conventions the v2 report and simulation routes share.

Both read the detailed-save tables and create through the simulation
service. A failure the caller can act on is answered with its own message;
any other is logged by type and the locations of its innermost frames, never
by its message, which can carry bound SQL parameters.
"""

from __future__ import annotations

import contextlib
import logging
import traceback
from typing import TYPE_CHECKING, Any, TypeVar

from starlette.responses import JSONResponse

from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.v2.errors_support import (
    V2ErrorMapping,
    V2ErrorResponse,
    run_v2_operation,
    v2_missing_parameters_response,
)
from policyengine_api.services.v2.household_calculations.validators import (
    HouseholdCalculationYearError,
)
from policyengine_api.services.v2.households.validators import HouseholdNotFoundError
from policyengine_api.services.v2.policies.validators import (
    PolicyNotFoundError,
    PolicyParametersMissingError,
)
from policyengine_api.services.v2.simulation_service.types import (
    SimulationServiceAnswerUnreadableError,
    SimulationServiceInternalError,
    SimulationServiceInvalidRequestError,
    SimulationServiceUnavailableError,
)
from policyengine_api.services.v2.simulation_service.validators import (
    EconomyCalculationsUnsupportedError,
    HouseholdCalculationsUnsupportedError,
    SubmissionStorageError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


logger = logging.getLogger(__name__)

# A submission's refusals a caller can act on carry their own message and are
# not logged.
SUBMISSION_REFUSALS: tuple[type[Exception], ...] = (
    PolicyNotFoundError,
    HouseholdNotFoundError,
    EconomyCalculationsUnsupportedError,
    HouseholdCalculationsUnsupportedError,
    HouseholdCalculationYearError,
    SimulationServiceInvalidRequestError,
)
# How the simulation service's answers and the submission checks are answered.
# The service's failure (500), an unreadable created answer, an answer lost
# after sending, a proxy's 502 or 504, a 503 that cannot be read or names
# only another record, and any status the client does not expect are a 502,
# as for household calculations: the record exists, or may, and a 503 says
# the service created nothing. The message of each but the unreadable
# created answer asks the caller to submit again, and says this creates a
# second record if the first request went through. The service's 503 naming
# the record it created and failed is still a 503, and each create route
# answers it with the record's ID (``unavailable_after_creation_answer``).
SUBMISSION_ERROR_MAPPINGS = (
    V2ErrorMapping((PolicyNotFoundError, HouseholdNotFoundError), 404),
    V2ErrorMapping(
        (
            EconomyCalculationsUnsupportedError,
            HouseholdCalculationsUnsupportedError,
            HouseholdCalculationYearError,
            SimulationServiceInvalidRequestError,
        ),
        422,
    ),
    V2ErrorMapping(
        (SimulationServiceInternalError, SimulationServiceAnswerUnreadableError), 502
    ),
    V2ErrorMapping((SimulationServiceUnavailableError,), 503),
    V2ErrorMapping(
        (V2ConfigurationError, SubmissionStorageError),
        503,
        "V2 storage is unavailable",
    ),
)

OperationT = TypeVar("OperationT")


def error_response(description: str) -> dict[str, Any]:
    """Return an OpenAPI response entry for an API v2 error."""
    return {"model": V2ErrorResponse, "description": description}


def _log_failure(event: str, error: Exception) -> None:
    """Record a failure's type and innermost frames; logging never fails a request."""
    with contextlib.suppress(Exception):
        frames = traceback.extract_tb(error.__traceback__)[-8:]
        logger.error(
            event,
            extra={
                "policyengine_attributes": {
                    "error_type": type(error).__name__,
                    "error_frames": "; ".join(
                        f"{frame.filename.rsplit('/', 1)[-1]}:{frame.lineno} "
                        f"in {frame.name}"
                        for frame in frames
                    ),
                }
            },
        )


def created_record_unreadable_answer(
    event: str, error: Exception, answer: V2ErrorResponse
) -> JSONResponse:
    """Log why a created record could not be read back, and answer 502.

    The simulation service created the record, so ``answer`` names it for the
    caller to read rather than submit again. The failure logged is the read's
    own, ``error``'s cause.
    """
    cause = error.__cause__
    _log_failure(event, cause if isinstance(cause, Exception) else error)
    return JSONResponse(status_code=502, content=answer.model_dump(mode="json"))


def unavailable_after_creation_answer(
    event: str, error: Exception, answer: V2ErrorResponse
) -> JSONResponse:
    """Log the simulation service's 503 that names a record it created, and answer 503.

    The service created the record, then failed its run, so ``answer`` gives
    the record's ID with the service's status and code, but not its reason,
    which may be an exception's text.
    """
    _log_failure(event, error)
    return JSONResponse(status_code=503, content=answer.model_dump(mode="json"))


def simulation_resource_operation(
    operation: Callable[[], OperationT],
    error_mappings: Sequence[V2ErrorMapping],
    *,
    refusals: tuple[type[Exception], ...],
    event: str,
    fallback_message: str,
) -> OperationT | JSONResponse:
    """Run one service call and answer its failure with a typed v2 error.

    A policy that sets parameters the running catalog version lacks answers
    422 with code ``missing_parameters``, naming them, whatever the route. A
    failure of a type in ``refusals`` is the caller's to act on and is not
    logged, nor is that 422; any other is logged under ``event``.
    """

    def logged() -> OperationT | JSONResponse:
        try:
            return operation()
        except PolicyParametersMissingError as error:
            return v2_missing_parameters_response(str(error), error.missing_parameters)
        except Exception as error:
            if not isinstance(error, refusals):
                _log_failure(event, error)
            raise

    return run_v2_operation(logged, error_mappings, fallback_message=fallback_message)
