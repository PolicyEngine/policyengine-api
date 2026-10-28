"""HTTP conventions shared by the Public API's clients of the simulation service.

Both the Simulation Entrypoint client of the v1 routes and the economy report
adapter of the v2 routes read the service's base URL from the environment and
send the current API request's correlation identifiers. Importing this module
has no side effects.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from policyengine_api.observability.identifiers import OBSERVABILITY_ID_HEADER
from policyengine_api.request_context import (
    REQUEST_ID_HEADER,
    current_observability_id,
    current_request_id,
)

if TYPE_CHECKING:
    import httpx


def required_base_url(env_name: str) -> str:
    """Return the base URL in ``env_name`` without a trailing slash.

    Raise ValueError when it is missing, or is not an absolute HTTP(S) URL free
    of credentials, a query and a fragment.
    """
    value = os.environ.get(env_name, "").strip()
    if not value:
        msg = f"{env_name} is required"
        raise ValueError(msg)

    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        msg = (
            f"{env_name} must be an absolute HTTP(S) base URL without "
            "credentials, a query, or a fragment"
        )
        raise ValueError(msg)
    return value.rstrip("/")


def attach_request_identifiers(request: httpx.Request) -> None:
    """Send the current API request's correlation identifiers with ``request``."""
    request_id = current_request_id()
    if request_id is not None:
        request.headers[REQUEST_ID_HEADER] = request_id
    observability_id = current_observability_id()
    if observability_id is not None:
        request.headers[OBSERVABILITY_ID_HEADER] = observability_id
