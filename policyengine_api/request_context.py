"""Request-scoped correlation identifiers shared by Flask and ASGI."""

from __future__ import annotations

import uuid
from contextvars import ContextVar

import flask
from policyengine_api.observability.identifiers import (
    generate_observability_id,
    normalize_observability_id,
)

REQUEST_ID_HEADER = "X-PolicyEngine-Request-Id"

_asgi_request_id: ContextVar[str | None] = ContextVar(
    "policyengine_api_request_id",
    default=None,
)
_asgi_observability_id: ContextVar[str | None] = ContextVar(
    "policyengine_api_observability_id",
    default=None,
)
_asgi_incoming_observability_id: ContextVar[str | None] = ContextVar(
    "policyengine_api_incoming_observability_id",
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


def current_observability_id() -> str | None:
    """Return the diagnostic correlation identifier for the current request."""

    if flask.has_request_context():
        return getattr(flask.g, "observability_id", None)
    return _asgi_observability_id.get()


def incoming_observability_id() -> str | None:
    """Return the validated identifier candidate supplied by the caller."""

    if flask.has_request_context():
        return getattr(flask.g, "incoming_observability_id", None)
    return _asgi_incoming_observability_id.get()


def _bind_observability_id(observability_id: str) -> str:
    if flask.has_request_context():
        flask.g.observability_id = observability_id
    else:
        _asgi_observability_id.set(observability_id)
    try:
        from policyengine_api.observability import get_runtime

        get_runtime().set_context(observability_id=observability_id)
    except Exception:
        pass
    return observability_id


def start_observability_id(value: object = None) -> str:
    """Bind the identifier for a newly accepted calculation or report."""

    current = current_observability_id()
    if current is not None:
        return current
    observability_id = resolve_observability_id(
        normalize_observability_id(value) or incoming_observability_id()
    )
    return _bind_observability_id(observability_id)


def adopt_observability_id(value: object) -> str | None:
    """Adopt a downstream identifier only when none is already bound."""

    current = current_observability_id()
    if current is not None:
        return current
    observability_id = normalize_observability_id(value)
    if observability_id is None:
        return None
    return _bind_observability_id(observability_id)


def restore_observability_id(value: object) -> str | None:
    """Bind a valid identifier read from durable functional state."""

    observability_id = normalize_observability_id(value)
    if observability_id is None:
        return current_observability_id()
    return _bind_observability_id(observability_id)


def resolve_observability_id(value: object) -> str:
    """Use a valid caller value or create a new diagnostic identifier."""

    return normalize_observability_id(value) or generate_observability_id()
