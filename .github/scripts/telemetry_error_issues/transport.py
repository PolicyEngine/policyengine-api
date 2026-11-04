"""HTTP requests and responses, the standard library transport, and API errors."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, NamedTuple
from urllib.error import HTTPError
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from collections.abc import Mapping

HTTP_TIMEOUT_SECONDS = 60
# A short code from an API error, such as "invalidQuery" or "Not Found". The
# error's message is never used, because it can repeat values from a record.
ERROR_REASON_PATTERN = re.compile(r"^[A-Za-z][A-Za-z ]{0,59}$")


class HttpRequest(NamedTuple):
    """An HTTP request for a transport to send."""

    method: str
    url: str
    headers: dict[str, str]
    body: bytes | None


class HttpResponse(NamedTuple):
    """An HTTP response, including error responses. Header names are lowercase."""

    status: int
    reason: str
    headers: Mapping[str, str]
    body: bytes


def urllib_transport(request: HttpRequest) -> HttpResponse:
    """Send a request with the standard library, returning HTTP errors too."""
    outgoing = Request(
        request.url,
        data=request.body,
        headers=request.headers,
        method=request.method,
    )
    try:
        response = urlopen(outgoing, timeout=HTTP_TIMEOUT_SECONDS)
    except HTTPError as error:
        with error:
            return HttpResponse(
                status=error.code,
                reason=str(error.reason),
                headers={name.lower(): value for name, value in error.headers.items()},
                body=error.read(),
            )
    with response:
        return HttpResponse(
            status=response.status,
            reason=response.reason,
            headers={name.lower(): value for name, value in response.headers.items()},
            body=response.read(),
        )


class ApiError(Exception):
    """An API request failed. The text holds only code-defined values."""

    service = "API"

    def __init__(
        self, message: str, *, status: int | None = None, reason: str | None = None
    ) -> None:
        """Keep the HTTP status and reason for the caller's summary."""
        super().__init__(message)
        self.status = status
        self.reason = reason

    @classmethod
    def from_response(cls, response: HttpResponse) -> ApiError:
        """Describe an error response by its status and reason, never its body."""
        reason = _error_reason(response)
        message = f"{cls.service} request failed: HTTP {response.status} {reason}"
        return cls(message, status=response.status, reason=reason)


def _error_reason(response: HttpResponse) -> str:
    """Return a Google API error's reason code, else the HTTP reason phrase."""
    try:
        payload = json.loads(response.body)
        reason = payload["error"]["errors"][0]["reason"]
    except (ValueError, KeyError, IndexError, TypeError):
        reason = None
    for candidate in (reason, response.reason):
        if isinstance(candidate, str) and ERROR_REASON_PATTERN.match(candidate):
            return candidate
    return "unknown"
