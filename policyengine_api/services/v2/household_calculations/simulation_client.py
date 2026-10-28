"""The simulation service's household calculation routes, checked by its models.

Calls go to the Cloud Run Simulation Entrypoint (``SIMULATION_ENTRYPOINT_URL``),
the only simulation service with these routes, over HTTP with the gateway
credentials the Public API already uses (``GATEWAY_AUTH_*``) and the request's
correlation headers.

The submission is checked against the generated client's submission model and
sent as built, and each answer is checked against the generated model for its
status and returned as decoded, both in their original key order, because
the generated models write their keys in an order of their own and the
household function lists warnings and calculated values in the household's
key order. The household's key order is the stored household's as the v2
database returns it, which orders each record's keys itself, so it can
differ from the order a caller sent.

A 400 is a refusal, whose reason the service gives (a household, policy or
catalog version it cannot find, or a household without a default year,
which the Public API checks first, or no household function for the
version); a 422 is the caller's data the service refuses, with its reason
as text (a parameter the catalog version lacks, or a stored policy value or
household the household functions cannot take) or one entry per request
field it refuses; anything else,
including a 503, no answer, an answer of another shape, a gateway token that
cannot be fetched or missing configuration, means the service is unavailable.

One client serves the process, so its connections and its gateway token are
reused across requests.
"""

from __future__ import annotations

from functools import lru_cache
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, TypeVar

import httpx
from policyengine_api_simulation_client.models.household_calculation_response import (
    HouseholdCalculationResponse,
)
from policyengine_api_simulation_client.models.household_calculation_submission import (
    HouseholdCalculationSubmission,
)
from policyengine_api_simulation_client.models.household_refusal_response import (
    HouseholdRefusalResponse,
)
from policyengine_api_simulation_client.models.household_request_field_error import (
    HouseholdRequestFieldError,
)
from policyengine_api_simulation_client.models.household_route_error import (
    HouseholdRouteError,
)
from policyengine_observability import (  # type: ignore[import-untyped]  # the package has no type information
    instrument_httpx,
)

from policyengine_api.libs.gateway_auth import (
    GatewayAuthError,
    GatewayAuthTokenProvider,
    GatewayBearerAuth,
    _require_all_or_none_gateway_auth_env,
    gateway_auth_required,
)
from policyengine_api.libs.simulation_entrypoint import (
    _attach_current_request_id,
    resolve_simulation_entrypoint_url,
)
from policyengine_api.observability import get_runtime
from policyengine_api.services.v2.household_calculations.types import (
    SimulationServiceInvalidRequestError,
    SimulationServiceRefusedError,
    SimulationServiceUnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from uuid import UUID

CALCULATIONS_PATH = "/v2/household-calculations"

REQUEST_TIMEOUT_SECONDS = 30.0
CLOUD_RUN_SIMULATION_ENTRYPOINT = "cloud_run_simulation_entrypoint"


def _send(send: Callable[[], httpx.Response]) -> httpx.Response:
    """Send one request; raise SimulationServiceUnavailableError if none answers."""
    try:
        return send()
    except (httpx.HTTPError, GatewayAuthError) as error:
        msg = "The simulation service could not be reached."
        raise SimulationServiceUnavailableError(msg) from error


ModelT = TypeVar("ModelT")


def _decoded(
    response: httpx.Response, read_model: Callable[[Mapping[str, Any]], ModelT]
) -> tuple[object, ModelT]:
    """Return the decoded body and the generated model read from it.

    Raise SimulationServiceUnavailableError when the body is not JSON or not
    of the model's shape.
    """
    try:
        body = response.json()
        return body, read_model(body)
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        msg = "The simulation service's answer could not be read."
        raise SimulationServiceUnavailableError(msg) from error


def _calculation(response: httpx.Response) -> dict[str, Any]:
    body, _calculation_model = _decoded(
        response, HouseholdCalculationResponse.from_dict
    )
    if not isinstance(body, dict):
        msg = "The simulation service's answer could not be read."
        raise SimulationServiceUnavailableError(msg)
    return body


def _invalid_request_reason(refusal: HouseholdRefusalResponse) -> str:
    """Return the service's reason, or each refused field and why.

    A field's location is given without the request's ``body`` prefix. Raise
    SimulationServiceUnavailableError for a refusal of another shape: the
    generated model keeps a ``detail`` it cannot read as text or fields.
    """
    detail: object = refusal.detail
    if isinstance(detail, str):
        reason = detail
    else:
        fields = (
            [item for item in detail if isinstance(item, HouseholdRequestFieldError)]
            if isinstance(detail, list)
            else []
        )
        if not isinstance(detail, list) or len(fields) != len(detail):
            msg = "The simulation service's answer could not be read."
            raise SimulationServiceUnavailableError(msg)
        reasons = []
        for item in fields:
            location = [str(part) for part in item.loc]
            if location[:1] == ["body"]:
                location = location[1:]
            reasons.append(f"{'.'.join(location)}: {item.msg}")
        reason = "; ".join(reasons) or "the request is invalid"
    return f"The simulation service cannot calculate this household: {reason}"


def _unavailable(status_code: int) -> SimulationServiceUnavailableError:
    return SimulationServiceUnavailableError(
        f"The simulation service answered {status_code}."
    )


def _gateway_auth() -> GatewayBearerAuth | None:
    """Return the gateway credentials, or None when none are set and none required."""
    _require_all_or_none_gateway_auth_env()
    token_provider = GatewayAuthTokenProvider()
    if token_provider.configured:
        return GatewayBearerAuth(token_provider)
    if gateway_auth_required():
        msg = "Gateway auth is required but GATEWAY_AUTH_* is not set."
        raise GatewayAuthError(msg)
    return None


class SimulationHouseholdClient:
    """Submit and read household calculations on the simulation service."""

    def __init__(
        self, base_url: str, *, httpx_args: dict[str, Any] | None = None
    ) -> None:
        """Call the service at ``base_url`` with these httpx client arguments."""
        http_client = httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS),
            event_hooks={"request": [_attach_current_request_id]},
            **(httpx_args or {}),
        )
        instrument_httpx(http_client, get_runtime())
        self._base_url = base_url.rstrip("/")
        self._http_client = http_client

    @property
    def base_url(self) -> str:
        """Return the simulation service's base URL, without a trailing slash."""
        return self._base_url

    @classmethod
    def from_environment(cls) -> SimulationHouseholdClient:
        """Call the configured Cloud Run Simulation Entrypoint with gateway auth.

        Raise SimulationServiceUnavailableError when the URL is missing or
        invalid, or gateway auth is partly configured or required but unset.
        """
        try:
            base_url = resolve_simulation_entrypoint_url(
                CLOUD_RUN_SIMULATION_ENTRYPOINT
            )
            auth = _gateway_auth()
        except (ValueError, GatewayAuthError) as error:
            msg = "The simulation service is not configured."
            raise SimulationServiceUnavailableError(msg) from error
        return cls(base_url, httpx_args={} if auth is None else {"auth": auth})

    def submit(self, submission: dict[str, Any]) -> dict[str, Any]:
        """Submit a calculation and return the service's calculation answer."""
        HouseholdCalculationSubmission.from_dict(submission)
        response = _send(
            lambda: self._http_client.post(CALCULATIONS_PATH, json=submission)
        )
        if response.status_code == HTTPStatus.ACCEPTED:
            return _calculation(response)
        if response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY:
            _body, invalid = _decoded(response, HouseholdRefusalResponse.from_dict)
            raise SimulationServiceInvalidRequestError(_invalid_request_reason(invalid))
        if response.status_code == HTTPStatus.BAD_REQUEST:
            _body, refusal = _decoded(response, HouseholdRouteError.from_dict)
            raise SimulationServiceRefusedError(refusal.detail)
        raise _unavailable(response.status_code)

    def read(self, calculation_id: UUID) -> dict[str, Any] | None:
        """Return the service's calculation answer, or None when it has none."""
        response = _send(
            lambda: self._http_client.get(f"{CALCULATIONS_PATH}/{calculation_id}")
        )
        if response.status_code == HTTPStatus.OK:
            return _calculation(response)
        if response.status_code == HTTPStatus.NOT_FOUND:
            _decoded(response, HouseholdRouteError.from_dict)
            return None
        raise _unavailable(response.status_code)


@lru_cache(maxsize=1)
def process_simulation_household_client() -> SimulationHouseholdClient:
    """Return the process's client, built from the environment on first use.

    A configuration error is raised again on the next call, not kept.
    """
    return SimulationHouseholdClient.from_environment()
