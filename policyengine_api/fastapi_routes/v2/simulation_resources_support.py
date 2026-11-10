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

from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.v2.errors_support import (
    V2ErrorMapping,
    V2ErrorResponse,
    run_v2_operation,
)
from policyengine_api.services.v2.policies.validators import PolicyNotFoundError
from policyengine_api.services.v2.simulation_service.types import (
    SimulationServiceAnswerUnreadableError,
    SimulationServiceInternalError,
    SimulationServiceRefusalError,
    SimulationServiceUnavailableError,
)
from policyengine_api.services.v2.simulation_service.validators import (
    EconomyCalculationsUnsupportedError,
    SubmissionStorageError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from starlette.responses import JSONResponse


logger = logging.getLogger(__name__)

# A submission's refusals a caller can act on carry their own message and are
# not logged.
SUBMISSION_REFUSALS: tuple[type[Exception], ...] = (
    PolicyNotFoundError,
    EconomyCalculationsUnsupportedError,
    SimulationServiceRefusalError,
)
# How the simulation service's answers and the submission checks are answered.
# An internal error or an unreadable created answer is a 500, not a 503: the
# record may exist, so the caller must not be invited to submit again.
SUBMISSION_ERROR_MAPPINGS = (
    V2ErrorMapping((PolicyNotFoundError,), 404),
    V2ErrorMapping(
        (EconomyCalculationsUnsupportedError, SimulationServiceRefusalError), 422
    ),
    V2ErrorMapping(
        (SimulationServiceInternalError, SimulationServiceAnswerUnreadableError), 500
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


def simulation_resource_operation(
    operation: Callable[[], OperationT],
    error_mappings: Sequence[V2ErrorMapping],
    *,
    refusals: tuple[type[Exception], ...],
    event: str,
    fallback_message: str,
) -> OperationT | JSONResponse:
    """Run one service call and answer its failure with a typed v2 error.

    A failure of a type in ``refusals`` is the caller's to act on and is not
    logged; any other is logged under ``event``.
    """

    def logged() -> OperationT:
        try:
            return operation()
        except Exception as error:
            if not isinstance(error, refusals):
                _log_failure(event, error)
            raise

    return run_v2_operation(logged, error_mappings, fallback_message=fallback_message)
