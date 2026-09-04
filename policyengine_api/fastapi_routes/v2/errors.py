"""Shared error response contract for all native API v2 routes."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints
from starlette.responses import JSONResponse


class V2RequestTooLargeError(ValueError):
    """Raised when an API v2 request exceeds its documented byte limit."""


class V2ErrorResponse(BaseModel):
    """Strict error envelope shared by every API v2 resource."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["error"] = "error"
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def v2_error_response(status_code: int, message: str) -> JSONResponse:
    """Serialize one API v2 error without resource-path dispatch."""

    error = V2ErrorResponse(message=message)
    return JSONResponse(
        status_code=status_code,
        content=error.model_dump(mode="json"),
    )
