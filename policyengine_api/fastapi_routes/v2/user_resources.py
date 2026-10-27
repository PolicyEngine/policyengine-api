"""Shared HTTP conventions for user-owned API v2 resources."""

from __future__ import annotations

import contextlib
import logging
import traceback
from typing import TYPE_CHECKING, Any, NamedTuple, TypeVar

# FastAPI reads the request-size dependency's annotations when routes are
# registered, so Request must exist at runtime.
from fastapi import Request  # noqa: TC002
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.v2.errors import (
    BEARER_CHALLENGE,
    V2ErrorResponse,
    V2RequestTooLargeError,
    v2_error_response,
)
from policyengine_api.services.v2.associations.validators import (
    AssociationConflictError,
    AssociationLinkNotFoundError,
    AssociationNotFoundError,
    AssociationReferenceConflictError,
)
from policyengine_api.services.v2.economy_reports.types import (
    SimulationServiceUnavailableError,
)
from policyengine_api.services.v2.identity.validators import (
    StandardUserRequiresSignInError,
)
from policyengine_api.services.v2.legacy_refs.validators import (
    LegacyReferenceNotFoundError,
)
from policyengine_api.services.v2.simulation_refs.validators import (
    SimulationReferenceNotFoundError,
)
from policyengine_api.services.v2.user_accounts.validators import (
    AccountDeletionUnavailableError,
    AccountEditRequiresSignInError,
    AccountIdentityDeletionError,
    AccountNotFoundError,
)
from policyengine_api.services.v2.user_households.validators import (
    AssociationHouseholdNotFoundError,
)
from policyengine_api.services.v2.user_policies.validators import (
    AssociationPolicyNotFoundError,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from starlette.responses import JSONResponse

MAXIMUM_USER_WRITE_REQUEST_BYTES = 256 * 1024


def request_size_limit(
    maximum_bytes: int, *, label: str
) -> Callable[[Request], Awaitable[None]]:
    """Build a dependency that bounds declared and actual request body bytes.

    It runs after the router-level authentication dependency, so an
    unauthenticated request still gets 401 first.
    """

    async def enforce(request: Request) -> None:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError as error:
                msg = "Request Content-Length is invalid"
                raise V2RequestTooLargeError(msg) from error
            if declared_length > maximum_bytes:
                msg = f"Request body exceeds {label}"
                raise V2RequestTooLargeError(msg)
        if len(await request.body()) > maximum_bytes:
            msg = f"Request body exceeds {label}"
            raise V2RequestTooLargeError(msg)

    return enforce


enforce_user_write_request_size = request_size_limit(
    MAXIMUM_USER_WRITE_REQUEST_BYTES, label="256 KiB"
)


USER_RESOURCE_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {
        "model": V2ErrorResponse,
        "description": "The supplied references or countries contradict each other.",
    },
    401: {
        "model": V2ErrorResponse,
        "description": (
            "A valid bearer access token, or a canonical UUID in the "
            "PolicyEngine-Unauthenticated-User header, is required; that UUID "
            "may not name a signed-in account. The response carries "
            "WWW-Authenticate: Bearer."
        ),
    },
    403: {
        "model": V2ErrorResponse,
        "description": (
            "Machine (client-credentials) principals are not permitted, and "
            "unauthenticated users cannot edit account details."
        ),
    },
    404: {
        "model": V2ErrorResponse,
        "description": "The record does not exist or belongs to another user.",
    },
    409: {
        "model": V2ErrorResponse,
        "description": (
            "The change conflicts with stored state, such as a record maintained "
            "by the v1 saved-policy mirror."
        ),
    },
    413: {
        "model": V2ErrorResponse,
        "description": "The request body exceeds 256 KiB.",
    },
    422: {
        "model": V2ErrorResponse,
        "description": (
            "The request does not match the schema, or a referenced v1 artifact, "
            "v2 report or simulation, or linked record does not exist."
        ),
    },
    500: {
        "model": V2ErrorResponse,
        "description": "The operation could not be completed.",
    },
    503: {
        "model": V2ErrorResponse,
        "description": (
            "User authentication, persistence or the simulation service is unavailable."
        ),
    },
}

logger = logging.getLogger(__name__)

OperationT = TypeVar("OperationT")


def _log_failure(event: str, error: Exception) -> None:
    """Record a failure without its message.

    Exception messages can carry bound SQL parameters or token claims, so only
    the type and the innermost frame locations are logged. Logging never
    changes the response.
    """
    # Observability must not alter the response.
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


class UserResourceFailure(NamedTuple):
    """The API v2 error response for one family of user-route service errors.

    Without a ``message``, the response carries the error's own message. A
    ``logged_event`` records the failure, without its message, under that name.
    """

    error_types: tuple[type[Exception], ...]
    status_code: int
    message: str | None = None
    headers: Mapping[str, str] | None = None
    logged_event: str | None = None


# Checked in order, so a subclass is listed before any base it shares a status
# with, and IntegrityError before the SQLAlchemyError it specializes.
USER_RESOURCE_FAILURES: tuple[UserResourceFailure, ...] = (
    UserResourceFailure(
        (StandardUserRequiresSignInError,),
        401,
        headers={"WWW-Authenticate": BEARER_CHALLENGE},
    ),
    UserResourceFailure((AccountEditRequiresSignInError,), 403),
    UserResourceFailure((AssociationReferenceConflictError,), 400),
    UserResourceFailure(
        (
            LegacyReferenceNotFoundError,
            SimulationReferenceNotFoundError,
            AssociationLinkNotFoundError,
        ),
        422,
    ),
    UserResourceFailure(
        (
            AssociationNotFoundError,
            AssociationPolicyNotFoundError,
            AssociationHouseholdNotFoundError,
            AccountNotFoundError,
        ),
        404,
    ),
    UserResourceFailure((AssociationConflictError,), 409),
    UserResourceFailure(
        (IntegrityError,), 409, "The record conflicts with stored state"
    ),
    UserResourceFailure((AccountIdentityDeletionError,), 502),
    UserResourceFailure((AccountDeletionUnavailableError,), 503),
    UserResourceFailure(
        (SimulationServiceUnavailableError,),
        503,
        "The simulation service is unavailable",
        logged_event="v2_user_simulation_service_unavailable",
    ),
    # Schema drift and rejected data surface here too, so keep a record.
    UserResourceFailure(
        (V2ConfigurationError, SQLAlchemyError),
        503,
        "V2 user persistence is unavailable",
        logged_event="v2_user_persistence_unavailable",
    ),
)


def _user_failure_response(error: Exception) -> JSONResponse:
    """Answer a failure with its first matching typed error, or a logged 500."""
    for failure in USER_RESOURCE_FAILURES:
        if isinstance(error, failure.error_types):
            if failure.logged_event is not None:
                _log_failure(failure.logged_event, error)
            message = str(error) if failure.message is None else failure.message
            return v2_error_response(
                failure.status_code, message, headers=failure.headers
            )
    _log_failure("v2_user_operation_failed", error)
    return v2_error_response(500, "V2 user operation failed")


def user_resource_operation(
    operation: Callable[[], OperationT],
) -> OperationT | JSONResponse:
    """Run one service call and map typed failures to secret-safe errors."""
    try:
        return operation()
    except Exception as error:  # noqa: BLE001  # return a secret-safe typed error
        return _user_failure_response(error)
