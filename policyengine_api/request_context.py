"""Request-scoped correlation identifiers shared by Flask and ASGI."""

from __future__ import annotations

import uuid
from contextvars import ContextVar

import flask

REQUEST_ID_HEADER = "X-PolicyEngine-Request-Id"

_asgi_request_id: ContextVar[str | None] = ContextVar(
    "policyengine_api_request_id",
    default=None,
)


def generate_request_id() -> str:
    """Generate an API request correlation identifier."""

    return uuid.uuid4().hex


def current_request_id() -> str | None:
    """Return the correlation identifier for the current request, if any."""

    if flask.has_request_context():
        return getattr(flask.g, "request_id", None)
    return _asgi_request_id.get()
