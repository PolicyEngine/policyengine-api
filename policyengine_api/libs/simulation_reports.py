"""Create simulations and reports through the simulation service.

``SimulationServiceReportClient`` is the ``SimulationServiceClient`` of the
v2 simulation and report routes. It posts to the Cloud Run simulation
service's ``POST /simulations`` and ``POST /reports``, at
``SIMULATION_ENTRYPOINT_URL`` whatever ``SIM_ENTRYPOINT`` selects for the v1
economy routes, through the HTTP client ``SimulationEntrypointClient``
builds: the same gateway credentials (``GATEWAY_AUTH_*``), request and
observability ID headers, transport and instrumentation as every other
simulation call.

A simulation request names the country, ``simulation_type`` (``economy``),
the year, the region code, the dataset name (null for the region's default),
and the stored policy and dynamic (null for current law). A report request
names the country, ``report_type`` (``economy``), the label and description,
the year, region and dataset its two simulations share, each simulation's
policy and dynamic, ``include_cliffs``, and the SPM settings only when the
caller gave them. Neither names a PolicyEngine.py version: the simulation
service runs its default worker's. The simulation service answers:

- 201 or 202 with the created record's ID and its first run's ID. One whose
  body cannot be read is SimulationServiceAnswerUnreadableError: the record
  exists, so the caller must not be invited to submit again;
- 422 with its reasons when it refuses the caller's data, as text or one
  per field as FastAPI writes them, and 400 with its reason when a row the
  request names does not exist (a region, dataset or dynamic; the Public
  API checks the country and policies first): SimulationServiceRefusalError;
- 500 when it failed, possibly after creating the record:
  SimulationServiceInternalError;
- anything else (503 when it cannot read its manifest or database, Modal
  refuses the call, or its default worker runs another version during a
  release): the service is unavailable (SimulationServiceUnavailableError),
  as it is for no answer, a refusal of another shape, a gateway token that
  cannot be fetched and missing configuration.

Wiring the generated simulation client: ``post_simulation`` and
``post_report`` are the only code that sends a request, and each returns the
status and body, which the rest of this module reads. Once a
``policyengine-api-simulation-client`` release has the two routes, depend on
that release and make each function call the generated operation, as its
docstring says.
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
from policyengine_api.services.v2.simulation_service.types import (
    SimulationServiceAnswerUnreadableError,
    SimulationServiceInternalError,
    SimulationServiceRefusalError,
    SimulationServiceUnavailableError,
    SubmittedReport,
    SubmittedSimulation,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from policyengine_api.services.v2.simulation_service.types import (
        EconomyReportCreationInput,
        EconomySimulationCreationInput,
        PolicyChoice,
    )

SIMULATIONS_PATH = "/simulations"
REPORTS_PATH = "/reports"
CLOUD_RUN_SIMULATION_ENTRYPOINT = "cloud_run_simulation_entrypoint"
CREATED_STATUSES = frozenset({HTTPStatus.CREATED, HTTPStatus.ACCEPTED})
REFUSAL_STATUSES = frozenset({HTTPStatus.BAD_REQUEST, HTTPStatus.UNPROCESSABLE_ENTITY})
UNREACHABLE = "The simulation service could not be reached."


@dataclass(frozen=True)
class SimulationAnswer:
    """The simulation service's answer: its HTTP status and body."""

    status_code: int
    content: bytes


class _AnswerModel(BaseModel):
    """Base for the simulation service's answers; fields it adds are ignored."""

    model_config = ConfigDict(extra="ignore", frozen=True)


class _CreatedSimulation(_AnswerModel):
    simulation_id: UUID
    simulation_run_id: UUID


class _CreatedReport(_AnswerModel):
    report_id: UUID
    report_run_id: UUID


class _RefusedField(_AnswerModel):
    """One request field the simulation service refuses, and why."""

    loc: list[str | int]
    msg: str


class _Refusal(_AnswerModel):
    """A refusal's body: a reason, or each refused request field."""

    detail: str | list[_RefusedField]


def _policy_choice(choice: PolicyChoice) -> dict[str, str | None]:
    return {
        "policy_id": None if choice.policy_id is None else str(choice.policy_id),
        "dynamic_id": None if choice.dynamic_id is None else str(choice.dynamic_id),
    }


def simulation_request(simulation: EconomySimulationCreationInput) -> dict[str, Any]:
    """Return the simulation service's request body for the simulation."""
    return {
        "country": simulation.country_id,
        "simulation_type": simulation.kind,
        "year": simulation.year,
        "region_code": simulation.region_code,
        "dataset_name": simulation.dataset_name,
        **_policy_choice(simulation),
    }


def report_request(report: EconomyReportCreationInput) -> dict[str, Any]:
    """Return the simulation service's request body for the report.

    ``spm`` is sent only when the caller gave it.
    """
    body: dict[str, Any] = {
        "country": report.country_id,
        "report_type": report.kind,
        "label": report.label,
        "description": report.description,
        "year": report.year,
        "region_code": report.region_code,
        "dataset_name": report.dataset_name,
        "baseline": _policy_choice(report.baseline),
        "reform": _policy_choice(report.reform),
        "include_cliffs": report.include_cliffs,
    }
    if report.spm is not None:
        body["spm"] = report.spm.model_dump(mode="json")
    return body


def post_simulation(
    http_client: httpx.Client, body: dict[str, Any]
) -> SimulationAnswer:
    """Send one simulation to the simulation service and return its answer.

    Raise httpx.HTTPError when no answer arrives, and GatewayAuthError when
    the gateway token cannot be fetched. ``http_client`` has the service's
    base URL. To send through the generated client instead, this body
    becomes (the operation and model names are those the simulation
    service's OpenAPI document gives the route)::

        client = Client(base_url=str(http_client.base_url))
        client.set_httpx_client(http_client)
        response = create_simulation.sync_detailed(
            client=client, body=SimulationRequest.from_dict(body)
        )
        return SimulationAnswer(int(response.status_code), response.content)
    """
    response = http_client.post(SIMULATIONS_PATH, json=body)
    return SimulationAnswer(status_code=response.status_code, content=response.content)


def post_report(http_client: httpx.Client, body: dict[str, Any]) -> SimulationAnswer:
    """Send one report to the simulation service and return its answer.

    As ``post_simulation``; with the generated client, the operation is the
    report route's (``create_report.sync_detailed`` with
    ``ReportRequest.from_dict(body)``).
    """
    response = http_client.post(REPORTS_PATH, json=body)
    return SimulationAnswer(status_code=response.status_code, content=response.content)


def _refusal_reason(refusal: _Refusal) -> str:
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


def _raise_for_refusal(answer: SimulationAnswer) -> None:
    """Raise the error a refusal, a failure or another answer means."""
    if answer.status_code in REFUSAL_STATUSES:
        try:
            refusal = _Refusal.model_validate_json(answer.content)
        except ValidationError as error:
            msg = f"The simulation service answered {answer.status_code} unreadably."
            raise SimulationServiceUnavailableError(msg) from error
        msg = (
            "The simulation service cannot run this request: "
            f"{_refusal_reason(refusal)}"
        )
        raise SimulationServiceRefusalError(msg)
    if answer.status_code == HTTPStatus.INTERNAL_SERVER_ERROR:
        msg = "The simulation service failed while creating the record."
        raise SimulationServiceInternalError(msg)
    msg = f"The simulation service answered {answer.status_code}."
    raise SimulationServiceUnavailableError(msg)


class SimulationServiceReportClient:
    """Create simulations and reports through the simulation service."""

    def __init__(
        self,
        http_client: httpx.Client,
        *,
        send_simulation: Callable[
            [httpx.Client, dict[str, Any]], SimulationAnswer
        ] = post_simulation,
        send_report: Callable[
            [httpx.Client, dict[str, Any]], SimulationAnswer
        ] = post_report,
    ) -> None:
        """Send through ``send_simulation`` and ``send_report`` on ``http_client``.

        ``http_client`` has the service's base URL.
        """
        self._http_client = http_client
        self._send_simulation = send_simulation
        self._send_report = send_report

    @classmethod
    def from_environment(
        cls, *, transport: httpx.BaseTransport | None = None
    ) -> SimulationServiceReportClient:
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

    def _answer(
        self,
        send: Callable[[httpx.Client, dict[str, Any]], SimulationAnswer],
        body: dict[str, Any],
    ) -> SimulationAnswer:
        try:
            return send(self._http_client, body)
        except (httpx.HTTPError, GatewayAuthError) as error:
            raise SimulationServiceUnavailableError(UNREACHABLE) from error

    def submit_simulation(
        self, simulation: EconomySimulationCreationInput
    ) -> SubmittedSimulation:
        """Create the simulation and its first run; return their IDs."""
        answer = self._answer(self._send_simulation, simulation_request(simulation))
        if answer.status_code not in CREATED_STATUSES:
            _raise_for_refusal(answer)
        try:
            created = _CreatedSimulation.model_validate_json(answer.content)
        except ValidationError as error:
            msg = (
                "The simulation service created the simulation, but its answer "
                "could not be read."
            )
            raise SimulationServiceAnswerUnreadableError(msg) from error
        return SubmittedSimulation(
            simulation_id=created.simulation_id,
            simulation_run_id=created.simulation_run_id,
        )

    def submit_report(self, report: EconomyReportCreationInput) -> SubmittedReport:
        """Create the report, its simulations and runs; return the report's IDs."""
        answer = self._answer(self._send_report, report_request(report))
        if answer.status_code not in CREATED_STATUSES:
            _raise_for_refusal(answer)
        try:
            created = _CreatedReport.model_validate_json(answer.content)
        except ValidationError as error:
            msg = (
                "The simulation service created the report, but its answer could "
                "not be read."
            )
            raise SimulationServiceAnswerUnreadableError(msg) from error
        return SubmittedReport(
            report_id=created.report_id, report_run_id=created.report_run_id
        )


@lru_cache(maxsize=1)
def process_simulation_service_client() -> SimulationServiceReportClient:
    """Return the process's client, built from the environment on first use.

    Its connections and gateway token are reused across requests. A
    configuration error is raised again on the next call, not kept.
    """
    return SimulationServiceReportClient.from_environment()
