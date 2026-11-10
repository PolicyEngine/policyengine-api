"""Submit household calculations to the simulation service.

``SimulationHouseholdCalculationClient`` is the household calculation
service's ``HouseholdCalculationSubmitter``. It posts a calculation to the
Cloud Run simulation service's ``POST /household-calculations``, at
``SIMULATION_ENTRYPOINT_URL`` whatever ``SIM_ENTRYPOINT`` selects for the
economy routes, through the HTTP client ``SimulationEntrypointClient`` builds:
the same gateway credentials (``GATEWAY_AUTH_*``), request and observability
ID headers, transport and instrumentation as every other simulation call.

The request names the country, the stored household and the stored policy
(null for current law), ``add_missing_variables``, and the axes and SPM
settings only when the caller gave them. The simulation service answers:

- 202 with the new job's ID and status. A 202 whose body cannot be read
  is SimulationServiceAnswerUnreadableError: the job exists, so the caller
  must not be invited to submit again;
- 422 with its reasons when it refuses the caller's data (a malformed
  request, or one its household contract refuses), one per field as
  FastAPI writes them: the reasons reach the caller as
  SimulationServiceInvalidRequestError;
- 500 (``internal_error``) when it failed, possibly after creating the job:
  SimulationServiceInternalError, which the caller must not resubmit after;
- anything else (400 for a household, policy or catalog version it cannot
  find, which the Public API checks first; 503 when it cannot read its
  manifest or database or Modal refuses the call, failing the job it
  names): the service is unavailable (SimulationServiceUnavailableError),
  with its ``code`` and reason when it gives them, as it is for no answer,
  a refusal of another shape, a gateway token that cannot be fetched and
  missing configuration. No answer means a connection never made
  (``ConnectError``, ``ConnectTimeout``, ``PoolTimeout``); once the request
  may have been sent, a lost answer (a read timeout, a dropped connection) is
  SimulationServiceAnswerUnreadableError, since the job may exist, and so is
  a 502 or 504 a proxy in front of the service answers in its place.

Each submission carries the request's ID and observability ID headers. The
observability ID is the request's own, else the caller's, else a new one,
which ``submit`` binds in the current context once the Public API's checks
have passed, as the Public API's own household calculations bind one when
they accept a calculation; the simulation service passes it to the household
function. The route reads it from that context and returns it in the
``X-PolicyEngine-Observability-Id`` header of every answer given once the
call was attempted, since a synchronous route runs in a copy of the request
context that the response middleware doesn't see. It is the attempt's ID,
which the service never received after a connection never made or a gateway
token that couldn't be fetched.

Wiring the generated simulation client: ``post_household_calculation`` is the
only code that sends the request, and it returns the status and body, which
the rest of this module reads. Once a ``policyengine-api-simulation-client``
release has the household calculation route, depend on that release and make
the function call the generated operation, as its docstring says.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from policyengine_api.libs.gateway_auth import GatewayAuthError
from policyengine_api.libs.simulation_entrypoint import SimulationEntrypointClient
from policyengine_api.request_context import start_observability_id
from policyengine_api.services.v2.household_calculations.types import (
    HouseholdCalculationAccepted,
    HouseholdJobStatusName,
    SimulationServiceAnswerUnreadableError,
    SimulationServiceInternalError,
    SimulationServiceInvalidRequestError,
    SimulationServiceUnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from policyengine_api.services.v2.household_calculations.types import (
        HouseholdCalculationInput,
    )

HOUSEHOLD_CALCULATIONS_PATH = "/household-calculations"
CLOUD_RUN_SIMULATION_ENTRYPOINT = "cloud_run_simulation_entrypoint"
UNREADABLE_ANSWER = "The simulation service's answer could not be read."
UNREADABLE_ACCEPTANCE = (
    "The simulation service accepted the calculation, but its answer could not be read."
)
# The service never answers 502 or 504 itself: a proxy in front of it, such as
# Cloud Run's front end, answers them in its place, possibly after the
# service created the job.
PROXY_STAND_IN_STATUSES = frozenset(
    {HTTPStatus.BAD_GATEWAY, HTTPStatus.GATEWAY_TIMEOUT}
)
# Transport errors raised before the request could reach the service. After
# any other, the service may have received the submission and created the job.
CONNECTION_NEVER_MADE = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


@dataclass(frozen=True)
class SimulationAnswer:
    """The simulation service's answer: its HTTP status and body."""

    status_code: int
    content: bytes


class _AnswerModel(BaseModel):
    """Base for the simulation service's answers; fields it adds are ignored."""

    model_config = ConfigDict(extra="ignore", frozen=True)


class _AcceptedJob(_AnswerModel):
    """The 202 body: the job the simulation service inserted, and its status."""

    job_id: UUID
    status: HouseholdJobStatusName


class _RefusedField(_AnswerModel):
    """One request field the simulation service refuses, and why."""

    loc: list[str | int]
    msg: str


class _Refusal(_AnswerModel):
    """A refusal's body: a reason, or each refused request field.

    A 400 or 503 also names its ``code``, and a 503 after Modal refused the
    call names the household job it failed.
    """

    detail: str | list[_RefusedField]
    code: str | None = None
    household_job_id: UUID | None = None


def household_calculation_request(
    calculation: HouseholdCalculationInput,
) -> dict[str, Any]:
    """Return the simulation service's request body for the calculation.

    ``axes`` and ``spm`` are sent only when the caller gave them; each axis
    and the SPM settings keep only the fields the caller gave.
    """
    body: dict[str, Any] = {
        "country": calculation.country_id,
        "household_id": str(calculation.household_id),
        "policy_id": (
            None if calculation.policy_id is None else str(calculation.policy_id)
        ),
        "add_missing_variables": calculation.add_missing_variables,
    }
    if calculation.axes is not None:
        body["axes"] = [
            [axis.model_dump(mode="json", exclude_unset=True) for axis in group]
            for group in calculation.axes
        ]
    if calculation.spm is not None:
        body["spm"] = calculation.spm.model_dump(mode="json")
    return body


def post_household_calculation(
    http_client: httpx.Client, body: dict[str, Any]
) -> SimulationAnswer:
    """Send one submission to the simulation service and return its answer.

    Raise httpx.HTTPError when no answer arrives, and GatewayAuthError when
    the gateway token cannot be fetched. ``http_client`` has the service's
    base URL. To send through the generated client instead, this body
    becomes, with ``Client`` from ``policyengine_api_simulation_client``,
    ``submit_household_calculation`` from its ``api.default`` package and
    ``HouseholdCalculationRequest`` from its ``models``, the names the
    simulation service's OpenAPI document gives the route::

        client = Client(base_url=str(http_client.base_url))
        client.set_httpx_client(http_client)
        response = submit_household_calculation.sync_detailed(
            client=client, body=HouseholdCalculationRequest.from_dict(body)
        )
        return SimulationAnswer(int(response.status_code), response.content)
    """
    response = http_client.post(HOUSEHOLD_CALCULATIONS_PATH, json=body)
    return SimulationAnswer(status_code=response.status_code, content=response.content)


def _invalid_request_reason(refusal: _Refusal) -> str:
    """Return the service's reason, or each refused field and why.

    A field's location is given without the request's ``body`` prefix.
    """
    if isinstance(refusal.detail, str):
        reason = refusal.detail
    else:
        reasons = []
        for refused_field in refusal.detail:
            location = [str(part) for part in refused_field.loc]
            if location[:1] == ["body"]:
                location = location[1:]
            reasons.append(f"{'.'.join(location)}: {refused_field.msg}")
        reason = "; ".join(reasons) or "the request is invalid"
    return f"The simulation service cannot calculate this household: {reason}"


def _refusal(answer: SimulationAnswer) -> _Refusal | None:
    try:
        return _Refusal.model_validate_json(answer.content)
    except ValidationError:
        return None


RESUBMISSION_WARNING = (
    "It may have created the job, so submitting again could create another."
)


def _internal_error(refusal: _Refusal | None) -> str:
    """Describe the service's failure, which may have created the job."""
    if refusal is None or not isinstance(refusal.detail, str):
        return f"The simulation service answered 500. {RESUBMISSION_WARNING}"
    code = "" if refusal.code is None else f" ({refusal.code})"
    return (
        f"The simulation service failed{code}: {refusal.detail} {RESUBMISSION_WARNING}"
    )


def _unavailable(answer: SimulationAnswer, refusal: _Refusal | None) -> str:
    """Describe an answer that means the service cannot calculate now."""
    if refusal is None or not isinstance(refusal.detail, str):
        return f"The simulation service answered {answer.status_code}."
    stated = (
        "refused the calculation"
        if answer.status_code == HTTPStatus.BAD_REQUEST
        else "is unavailable"
    )
    code = "" if refusal.code is None else f" ({refusal.code})"
    message = f"The simulation service {stated}{code}: {refusal.detail}"
    if refusal.household_job_id is not None:
        message += f"; it failed household job {refusal.household_job_id}"
    return message


class SimulationHouseholdCalculationClient:
    """Submit household calculations to the simulation service."""

    def __init__(
        self,
        http_client: httpx.Client,
        *,
        send: Callable[
            [httpx.Client, dict[str, Any]], SimulationAnswer
        ] = post_household_calculation,
    ) -> None:
        """Send through ``send`` on ``http_client``, which has the service's URL."""
        self._http_client = http_client
        self._send = send

    @classmethod
    def from_environment(
        cls, *, transport: httpx.BaseTransport | None = None
    ) -> SimulationHouseholdCalculationClient:
        """Call the configured Cloud Run simulation service with gateway auth.

        ``transport`` replaces the simulation transport, for tests. Raise
        SimulationServiceUnavailableError when ``SIMULATION_ENTRYPOINT_URL``
        is missing or invalid, or gateway auth is partly configured or
        required but unset.
        """
        try:
            entrypoint = SimulationEntrypointClient(
                CLOUD_RUN_SIMULATION_ENTRYPOINT, transport=transport
            )
        except (ValueError, GatewayAuthError) as error:
            msg = "The simulation service is not configured."
            raise SimulationServiceUnavailableError(msg) from error
        http_client = entrypoint.client
        http_client.base_url = httpx.URL(entrypoint.base_url)
        return cls(http_client)

    def submit(
        self, calculation: HouseholdCalculationInput
    ) -> HouseholdCalculationAccepted:
        """Submit the calculation and return the job the service created.

        Raise SimulationServiceInvalidRequestError with the service's reasons
        when it refuses the caller's data; SimulationServiceAnswerUnreadableError
        when it accepted the calculation but its answer cannot be read, or its
        answer was lost after the submission may have reached it;
        SimulationServiceInternalError when it failed (500); and
        SimulationServiceUnavailableError otherwise, including a connection
        never made.
        """
        start_observability_id()
        try:
            answer = self._send(
                self._http_client, household_calculation_request(calculation)
            )
        except (*CONNECTION_NEVER_MADE, GatewayAuthError) as error:
            msg = "The simulation service could not be reached."
            raise SimulationServiceUnavailableError(msg) from error
        except httpx.HTTPError as error:
            msg = (
                "The simulation service may have received the submission, but "
                f"its answer did not arrive ({type(error).__name__}). Check "
                "whether it created the job before submitting again."
            )
            raise SimulationServiceAnswerUnreadableError(msg) from error
        if answer.status_code == HTTPStatus.ACCEPTED:
            try:
                accepted = _AcceptedJob.model_validate_json(answer.content)
            except ValidationError as error:
                raise SimulationServiceAnswerUnreadableError(
                    UNREADABLE_ACCEPTANCE
                ) from error
            return HouseholdCalculationAccepted(
                calculation_id=accepted.job_id, status=accepted.status
            )
        refusal = _refusal(answer)
        if answer.status_code == HTTPStatus.UNPROCESSABLE_ENTITY:
            if refusal is None:
                raise SimulationServiceUnavailableError(UNREADABLE_ANSWER)
            raise SimulationServiceInvalidRequestError(_invalid_request_reason(refusal))
        if answer.status_code == HTTPStatus.INTERNAL_SERVER_ERROR:
            raise SimulationServiceInternalError(_internal_error(refusal))
        if answer.status_code in PROXY_STAND_IN_STATUSES:
            msg = (
                "The simulation service may have received the submission, but "
                f"{answer.status_code} was answered in its place. Check whether "
                "it created the job before submitting again."
            )
            raise SimulationServiceAnswerUnreadableError(msg)
        raise SimulationServiceUnavailableError(_unavailable(answer, refusal))


@lru_cache(maxsize=1)
def process_simulation_household_calculation_client() -> (
    SimulationHouseholdCalculationClient
):
    """Return the process's client, built from the environment on first use.

    Its connections and gateway token are reused across requests. A
    configuration error is raised again on the next call, not kept.
    """
    return SimulationHouseholdCalculationClient.from_environment()
