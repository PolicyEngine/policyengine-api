"""Shared error response contract for all native API v2 routes."""

import traceback
from collections.abc import Callable, Mapping, Sequence
from typing import Annotated, Literal, NamedTuple, TypeVar

from pydantic import BaseModel, ConfigDict, StringConstraints
from starlette.responses import JSONResponse

BEARER_CHALLENGE = "Bearer"
INVALID_TOKEN_BEARER_CHALLENGE = 'Bearer error="invalid_token"'  # noqa: S105  # a WWW-Authenticate challenge, not a secret


class V2RequestTooLargeError(ValueError):
    """Raised when an API v2 request exceeds its documented byte limit."""


class V2AuthenticationRequiredError(Exception):
    """Raised when a user route has no valid bearer access token (401)."""

    def __init__(self, message: str, *, invalid_token: bool = False) -> None:
        """Choose the WWW-Authenticate challenge sent with the 401.

        ``invalid_token`` marks a credential that was sent but rejected, which the
        challenge reports as ``error="invalid_token"``.
        """
        super().__init__(message)
        self.challenge = (
            INVALID_TOKEN_BEARER_CHALLENGE if invalid_token else BEARER_CHALLENGE
        )


class V2PermissionDeniedError(Exception):
    """Raised when an authenticated principal may not use a route (403)."""


class V2AuthenticationUnavailableError(Exception):
    """Raised when this deployment cannot authenticate users (503)."""


class V2ErrorResponse(BaseModel):
    """Strict error response shared by every API v2 resource."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["error"] = "error"
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def v2_error_response(
    status_code: int,
    message: str,
    *,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Serialize one API v2 error without resource-path dispatch."""
    error = V2ErrorResponse(message=message)
    return JSONResponse(
        status_code=status_code,
        content=error.model_dump(mode="json"),
        headers=dict(headers) if headers is not None else None,
    )


OperationT = TypeVar("OperationT")


class V2ErrorMapping(NamedTuple):
    """The API v2 error response for one family of service errors.

    Without a ``message``, the response carries the error's own message.
    """

    error_types: tuple[type[Exception], ...]
    status_code: int
    message: str | None = None


def run_v2_operation(
    operation: Callable[[], OperationT],
    error_mappings: Sequence[V2ErrorMapping],
    *,
    fallback_message: str,
) -> OperationT | JSONResponse:
    """Run ``operation``, answering a failure with the first matching v2 error.

    A failure that no mapping matches becomes a 500 with ``fallback_message``,
    so no unexpected detail reaches the response.
    """
    try:
        return operation()
    except Exception as error:  # noqa: BLE001  # return a secret-safe typed error
        for mapping in error_mappings:
            if isinstance(error, mapping.error_types):
                message = str(error) if mapping.message is None else mapping.message
                return v2_error_response(mapping.status_code, message)
        return v2_error_response(500, fallback_message)


def failure_log_attributes(error: BaseException) -> dict[str, str]:
    """Describe a failure for a log record without its message.

    Exception messages can carry bound SQL parameters or token claims, so the
    record holds the error's type and the locations of its innermost frames.
    """
    frames = traceback.extract_tb(error.__traceback__)[-8:]
    return {
        "error_type": type(error).__name__,
        "error_frames": "; ".join(
            f"{frame.filename.rsplit('/', 1)[-1]}:{frame.lineno} in {frame.name}"
            for frame in frames
        ),
    }
