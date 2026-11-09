"""The caller of each request, checked before route matching.

The ASGI shell (:mod:`policyengine_api.asgi_factory`) awaits
:func:`check_request_caller` for every request to a Flask or native route,
before routing. A request whose ``Authorization`` header is not a valid
credential gets :func:`authentication_required_response` there, and the route
never runs. Otherwise the shell binds the caller with
:func:`bind_request_caller`; Flask routes read it with
:func:`current_request_caller` from the context that the WSGI adapter copies
into their thread.

Both frameworks add :func:`caller_attributes` to the request's observability
record: ``caller.kind`` (``none``, ``server`` or ``user``) and, for a server,
``caller.client_id``. A request without a credential is served as before and
records nothing of its own; its record carries ``caller.kind=none``.

Each refusal is a runtime event at INFO, ``public_api_credential_refused``,
with its reason, the method, the path and the request ID the response
returns, never the header. A refused request to a Flask route never reaches
Flask, so this event is its only record. A token that cannot be checked is a
WARNING event, ``public_api_credential_check_unavailable``. They are runtime
events rather than standard-library log records because the deployed process
leaves the root logger at WARNING, which drops INFO records.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

from policyengine_api.libs.server_credentials import (
    NO_CREDENTIAL,
    CredentialCheckUnavailableError,
    CredentialRefusedError,
    RefusalReason,
    RequestCaller,
    identify_caller,
    load_server_credential_settings,
)
from policyengine_api.libs.user_auth import (
    UserAuthConfigurationError,
    load_user_auth_settings,
)

if TYPE_CHECKING:
    from policyengine_observability import ObservabilityRuntime
    from starlette.requests import Request

AUTHORIZATION_HEADER = "authorization"
CALLER_KIND_ATTRIBUTE = "caller.kind"
CALLER_CLIENT_ID_ATTRIBUTE = "caller.client_id"
AUTHENTICATION_REQUIRED_MESSAGE = "Authentication is required"
AUTHENTICATION_UNAVAILABLE_MESSAGE = "Authentication is unavailable"
BEARER_CHALLENGE = "Bearer"
REFUSAL_EVENT = "public_api_credential_refused"
UNAVAILABLE_EVENT = "public_api_credential_check_unavailable"

_request_caller: ContextVar[RequestCaller | None] = ContextVar(
    "policyengine_api_request_caller",
    default=None,
)


def authentication_required_response() -> Response:
    """Return the Public API's refusal of a request without a valid credential."""
    return JSONResponse(
        {"status": "error", "message": AUTHENTICATION_REQUIRED_MESSAGE},
        status_code=401,
        headers={"WWW-Authenticate": BEARER_CHALLENGE},
    )


def authentication_unavailable_response() -> Response:
    """Return the answer to a bearer token this deployment cannot check."""
    return JSONResponse(
        {"status": "error", "message": AUTHENTICATION_UNAVAILABLE_MESSAGE},
        status_code=503,
    )


def caller_attributes(caller: RequestCaller) -> dict[str, str]:
    """Return the observability attributes that identify ``caller``."""
    attributes = {CALLER_KIND_ATTRIBUTE: caller.kind.value}
    if caller.client_id is not None:
        attributes[CALLER_CLIENT_ID_ATTRIBUTE] = caller.client_id
    return attributes


def bind_request_caller(caller: RequestCaller) -> Token[RequestCaller | None]:
    """Bind ``caller`` to the current request; reset it with the token."""
    return _request_caller.set(caller)


def reset_request_caller(token: Token[RequestCaller | None]) -> None:
    """Restore the caller bound before :func:`bind_request_caller`."""
    _request_caller.reset(token)


def current_request_caller() -> RequestCaller | None:
    """Return the current request's checked caller, if the ASGI shell bound one."""
    return _request_caller.get()


def _identify(authorization: str) -> RequestCaller:
    """Load the settings and classify ``authorization``; may fetch signing keys."""
    return identify_caller(
        authorization,
        load_user_auth_settings(),
        load_server_credential_settings(),
    )


def _request_id_attributes(request: Request) -> dict[str, str]:
    request_id = getattr(request.state, "policyengine_request_id", None)
    return {"request.id": request_id} if isinstance(request_id, str) else {}


def _record_event(
    runtime: ObservabilityRuntime,
    name: str,
    *,
    severity: str,
    attributes: dict[str, str],
) -> None:
    # Telemetry must never fail the request.
    with contextlib.suppress(Exception):
        runtime.event(name, severity=severity, attributes=attributes)


def _record_refusal(
    runtime: ObservabilityRuntime,
    request: Request,
    reason: RefusalReason,
    *,
    client_id: str | None = None,
) -> None:
    attributes = {"refusal_reason": reason.value}
    if client_id is not None:
        attributes[CALLER_CLIENT_ID_ATTRIBUTE] = client_id
    attributes["http.request.method"] = request.method
    attributes["url.path"] = request.url.path
    attributes.update(_request_id_attributes(request))
    _record_event(runtime, REFUSAL_EVENT, severity="INFO", attributes=attributes)


def _record_unavailable(
    runtime: ObservabilityRuntime, request: Request, error: Exception
) -> None:
    attributes = {"error_type": type(error).__name__}
    attributes.update(_request_id_attributes(request))
    _record_event(runtime, UNAVAILABLE_EVENT, severity="WARNING", attributes=attributes)


async def check_request_caller(
    request: Request, runtime: ObservabilityRuntime
) -> RequestCaller | Response:
    """Return the request's caller, or the response that refuses its credential.

    A request without ``Authorization``, or with a blank one, has no
    credential. One with two or more ``Authorization`` headers is refused, so
    no layer can read a different one from the layer that checked it. A token
    is checked in a worker thread, because fetching signing keys blocks.
    """
    authorization_values = request.headers.getlist(AUTHORIZATION_HEADER)
    if len(authorization_values) > 1:
        _record_refusal(runtime, request, RefusalReason.DUPLICATE_HEADER)
        return authentication_required_response()
    authorization = authorization_values[0] if authorization_values else ""
    if not authorization.strip():
        return NO_CREDENTIAL
    try:
        return await run_in_threadpool(_identify, authorization)
    except CredentialRefusedError as refusal:
        _record_refusal(runtime, request, refusal.reason, client_id=refusal.client_id)
        return authentication_required_response()
    except (CredentialCheckUnavailableError, UserAuthConfigurationError) as error:
        _record_unavailable(runtime, request, error)
        return authentication_unavailable_response()
