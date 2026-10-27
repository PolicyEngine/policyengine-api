"""The simulation service's household calculation routes, through its client.

Calls go to the Cloud Run Simulation Entrypoint (``SIMULATION_ENTRYPOINT_URL``),
the only simulation service with these routes, with the gateway credentials
the Public API already uses (``GATEWAY_AUTH_*``) and the request's
correlation headers. A 400 is a refusal, whose reason the service gives; any
other failure, including a 503, no answer or missing configuration, means the
service is unavailable.

One client serves the process, so its connections and its gateway token are
reused across requests.
"""

from __future__ import annotations

from functools import lru_cache
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import httpx
from policyengine_api_simulation_client import AuthenticatedClient
from policyengine_api_simulation_client.api.default import (
    get_household_calculation,
    submit_household_calculation,
)
from policyengine_api_simulation_client.models.household_calculation_submission import (
    HouseholdCalculationSubmission,
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
    SimulationServiceRefusedError,
    SimulationServiceUnavailableError,
)

if TYPE_CHECKING:
    from uuid import UUID

REQUEST_TIMEOUT_SECONDS = 30.0
CLOUD_RUN_SIMULATION_ENTRYPOINT = "cloud_run_simulation_entrypoint"


def _answer(response: Any) -> tuple[int, object]:  # noqa: ANN401  # the generated client's Response
    try:
        body = httpx.Response(response.status_code, content=response.content).json()
    except ValueError:
        body = None
    return int(response.status_code), body


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


def _refusal_reason(body: object) -> str:
    reason = body.get("detail") if isinstance(body, dict) else None
    if isinstance(reason, str):
        return reason
    return "The simulation service refused the household calculation."


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
        # The generated routes take an AuthenticatedClient. Its fixed token is
        # sent only from an httpx client it builds itself; the one set here
        # authenticates through ``httpx_args`` (GatewayBearerAuth, which
        # fetches and renews the gateway token), so the empty token is unused.
        self._client = AuthenticatedClient(
            base_url=base_url, token=""
        ).set_httpx_client(http_client)

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
        try:
            response = submit_household_calculation.sync_detailed(
                client=self._client,
                body=HouseholdCalculationSubmission.from_dict(submission),
            )
        except httpx.HTTPError as error:
            msg = "The simulation service could not be reached."
            raise SimulationServiceUnavailableError(msg) from error
        status, body = _answer(response)
        if status == HTTPStatus.BAD_REQUEST:
            raise SimulationServiceRefusedError(_refusal_reason(body))
        if status != HTTPStatus.ACCEPTED or not isinstance(body, dict):
            msg = f"The simulation service answered {status}."
            raise SimulationServiceUnavailableError(msg)
        return body

    def read(self, calculation_id: UUID) -> dict[str, Any] | None:
        """Return the service's calculation answer, or None when it has none."""
        try:
            response = get_household_calculation.sync_detailed(
                calculation_id, client=self._client
            )
        except httpx.HTTPError as error:
            msg = "The simulation service could not be reached."
            raise SimulationServiceUnavailableError(msg) from error
        status, body = _answer(response)
        if status == HTTPStatus.NOT_FOUND:
            return None
        if status != HTTPStatus.OK or not isinstance(body, dict):
            msg = f"The simulation service answered {status}."
            raise SimulationServiceUnavailableError(msg)
        return body


@lru_cache(maxsize=1)
def process_simulation_household_client() -> SimulationHouseholdClient:
    """Return the process's client, built from the environment on first use.

    A configuration error is raised again on the next call, not kept.
    """
    return SimulationHouseholdClient.from_environment()
