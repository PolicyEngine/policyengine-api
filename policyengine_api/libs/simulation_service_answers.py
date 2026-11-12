"""Send requests to the simulation service, and read what every v2 route reads alike.

The Public API's v2 household calculation, report and simulation routes call
the Cloud Run simulation service's v2 routes
(``policyengine_api.libs.simulation_household_calculations`` and
``policyengine_api.libs.simulation_reports``). Each of those modules decides
what each of its route's answers means; this module holds what they share:

- the HTTP client, built by ``simulation_service_http_client`` from
  ``SimulationEntrypointClient`` at ``SIMULATION_ENTRYPOINT_URL``, with the
  gateway credentials (``GATEWAY_AUTH_*``), request and observability ID
  headers, transport and instrumentation of every other simulation call;
- the sorting of transport errors (``send_to_simulation_service``): a
  connection never made (``CONNECTION_NEVER_MADE``) or a gateway token that
  cannot be fetched means the service created nothing, so it is
  SimulationServiceUnavailableError; any other transport error may follow a
  request the service received, so it is
  SimulationServiceAnswerUnreadableError, asking the caller to submit again;
- the answer's status and body (``SimulationAnswer``), and the models its
  bodies are read with (``AnswerModel``, ``Refusal``, ``RefusedField``);
- the refusal's reason (``refusal_reason``), and the status and code a
  message gives in place of the service's reason (``status_and_code``), with
  the code only when it is a fixed identifier (``FIXED_IDENTIFIER``);
- the statuses a proxy in front of the service answers in its place
  (``PROXY_STAND_IN_STATUSES``), and, for the report and simulation client
  and the report re-run client, the statuses of a created record
  (``CREATED_STATUSES``), of a refusal (``REFUSAL_STATUSES``) and of an
  answer sent before the service's route writes anything
  (``SENT_BEFORE_ROUTE_STATUSES``), and the codes of a refusal of a row the
  Public API does not check (``CALLER_ROW_REFUSAL_CODES``);
- the messages for an answer lost after the request may have arrived
  (``answer_lost``) and for a failure after the service may have created
  what was submitted (``created_but_failed``), each ending with
  ``submit_again``'s sentence.

Each client still builds its own refusal messages, and its own message for
a 400 or 422 it cannot read, since the two routes answer them differently:
the household calculation client names a refusal's code only when it is a
fixed identifier, and the report and simulation client names any text
code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from policyengine_api.libs.gateway_auth import GatewayAuthError
from policyengine_api.libs.simulation_entrypoint import SimulationEntrypointClient
from policyengine_api.services.v2.simulation_service.types import (
    SimulationServiceAnswerUnreadableError,
    SimulationServiceUnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

CLOUD_RUN_SIMULATION_ENTRYPOINT = "cloud_run_simulation_entrypoint"
UNREACHABLE = "The simulation service could not be reached."
NOT_CONFIGURED = "The simulation service is not configured."
# The service never answers 502 or 504 itself: a proxy in front of it, such as
# Cloud Run's front end, answers them in its place, possibly after the
# service created what was submitted.
PROXY_STAND_IN_STATUSES = frozenset(
    {HTTPStatus.BAD_GATEWAY, HTTPStatus.GATEWAY_TIMEOUT}
)
# The statuses of a created record and of a refusal of the request.
CREATED_STATUSES = frozenset({HTTPStatus.CREATED, HTTPStatus.ACCEPTED})
REFUSAL_STATUSES = frozenset({HTTPStatus.BAD_REQUEST, HTTPStatus.UNPROCESSABLE_ENTITY})
# The codes of the simulation service's report and simulation routes' 400
# that name a row the caller chose, or a stored report names, and the Public
# API does not check: the region, the dataset, or a dynamic the catalog
# version its default worker runs does not have. Each is the caller's error
# and answers 422. Any other 400 is a state of the service, such as a catalog
# version missing while a release deploys, or a row the Public API already
# checked, and answers 503.
CALLER_ROW_REFUSAL_CODES = frozenset(
    {"unknown_region", "unknown_dataset", "unknown_dynamic"}
)
# Statuses the gateway, Cloud Run or the service's framework answers before
# the service's report and simulation routes run, so the service has created
# nothing: a call not authenticated or not allowed, a route or method the
# service does not have, a body over the size limit, and too many requests.
# A re-run route's own 404, for a record it does not find, also comes before
# any write. The route may have written rows before answering any other
# status the client does not expect.
SENT_BEFORE_ROUTE_STATUSES = frozenset(
    {
        HTTPStatus.UNAUTHORIZED,
        HTTPStatus.FORBIDDEN,
        HTTPStatus.NOT_FOUND,
        HTTPStatus.METHOD_NOT_ALLOWED,
        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        HTTPStatus.TOO_MANY_REQUESTS,
    }
)
# Transport errors raised before the request could reach the service. After
# any other, the service may have received the submission and created what
# it asks for.
CONNECTION_NEVER_MADE = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
# A code the service names may reach the caller without its reason only when
# it is a fixed identifier: lower-case letters, digits and underscores,
# starting with a letter, at most 64 characters. Any other, such as an
# exception's text, which could hold stored data, is left out.
FIXED_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{0,63}")
# Any JSON value, parsed by pydantic's parser, which has a depth limit.
ANY_JSON: TypeAdapter[Any] = TypeAdapter(Any)


@dataclass(frozen=True)
class SimulationAnswer:
    """The simulation service's answer: its HTTP status and body."""

    status_code: int
    content: bytes


class AnswerModel(BaseModel):
    """Base for the simulation service's answers; fields it adds are ignored."""

    model_config = ConfigDict(extra="ignore", frozen=True)


class RefusedField(AnswerModel):
    """One request field the simulation service refuses, and why."""

    loc: list[str | int]
    msg: str


class Refusal(AnswerModel):
    """A refusal's body: a reason, or each refused request field."""

    detail: str | list[RefusedField]


def simulation_service_http_client(
    *, transport: httpx.BaseTransport | None = None
) -> httpx.Client:
    """Return an HTTP client for the configured Cloud Run simulation service.

    The client has the service's base URL and gateway auth. ``transport``
    replaces the simulation transport, for tests. Raise
    SimulationServiceUnavailableError when ``SIMULATION_ENTRYPOINT_URL`` is
    missing or invalid, or gateway auth is partly configured or required but
    unset.
    """
    try:
        entrypoint = SimulationEntrypointClient(
            CLOUD_RUN_SIMULATION_ENTRYPOINT, transport=transport
        )
    except (ValueError, GatewayAuthError) as error:
        raise SimulationServiceUnavailableError(NOT_CONFIGURED) from error
    http_client = entrypoint.client
    http_client.base_url = httpx.URL(entrypoint.base_url)
    return http_client


def submit_again(submission: str, second: str) -> str:
    """Ask the caller to submit the ``submission`` again, which may create a second.

    No route finds what a submission created by what it was submitted with,
    so the caller cannot check whether the first request created a
    ``second``.
    """
    return (
        f"Submit the {submission} again; if the first request went through, "
        f"this creates a second {second}."
    )


def answer_lost(what_happened: str, submit_again_sentence: str) -> str:
    """Say the service may have received the request, but its answer was lost.

    ``what_happened`` names what came in place of a readable answer, such as
    the transport error's type or what a proxy answered.
    """
    return (
        "The simulation service may have received the request, but its answer "
        f"was lost ({what_happened}). {submit_again_sentence}"
    )


def created_but_failed(
    created: str, status_and_code_text: str, submit_again_sentence: str
) -> str:
    """Say the service may have created the ``created``, but failed.

    ``status_and_code_text`` is the service's status, and its code when that
    is a fixed identifier (``status_and_code``), never its reason, which may
    be an exception's text.
    """
    return (
        f"The simulation service may have created the {created}, but it failed "
        f"({status_and_code_text}). {submit_again_sentence}"
    )


def send_to_simulation_service(
    send: Callable[[httpx.Client, dict[str, Any]], SimulationAnswer],
    http_client: httpx.Client,
    body: dict[str, Any],
    *,
    submit_again_sentence: str,
) -> SimulationAnswer:
    """Send ``body`` through ``send`` and return the answer, whatever its status.

    Raise SimulationServiceUnavailableError when the connection was never
    made or the gateway token cannot be fetched, and
    SimulationServiceAnswerUnreadableError when the answer was lost after the
    request may have reached the service, whose message ends with
    ``submit_again_sentence``.
    """
    try:
        return send(http_client, body)
    except (*CONNECTION_NEVER_MADE, GatewayAuthError) as error:
        raise SimulationServiceUnavailableError(UNREACHABLE) from error
    except httpx.HTTPError as error:
        raise SimulationServiceAnswerUnreadableError(
            answer_lost(type(error).__name__, submit_again_sentence)
        ) from error


def parsed_body(answer: SimulationAnswer) -> object:
    """Return the answer's body as parsed JSON, or None when it is not JSON.

    pydantic's parser reports a body nested past its depth limit, or bytes
    that are not UTF-8, as a ValidationError, so no body can raise anything
    else.
    """
    try:
        return ANY_JSON.validate_json(answer.content)
    except ValidationError:
        return None


def fixed_identifier_code(body: object) -> str | None:
    """Return the body's ``code`` when it is a fixed identifier, else None.

    The body is parsed JSON (``parsed_body``); one that is not an object
    names no code.
    """
    code = body.get("code") if isinstance(body, dict) else None
    if isinstance(code, str) and FIXED_IDENTIFIER.fullmatch(code):
        return code
    return None


def status_and_code(status_code: int, code: str | None) -> str:
    """Return the status, and the code when there is one: ``503 manifest_unavailable``.

    Never the service's reason, which may be an exception's text.
    """
    if code is None:
        return str(status_code)
    return f"{status_code} {code}"


def refusal_reason(refusal: Refusal) -> str:
    """Return the service's reason, or each refused field and why.

    A field's location is given without the request's ``body`` prefix.
    """
    if isinstance(refusal.detail, str):
        return refusal.detail
    reasons = []
    for refused_field in refusal.detail:
        location = [str(part) for part in refused_field.loc]
        if location[:1] == ["body"]:
            location = location[1:]
        reasons.append(f"{'.'.join(location)}: {refused_field.msg}")
    return "; ".join(reasons) or "the request is invalid"
