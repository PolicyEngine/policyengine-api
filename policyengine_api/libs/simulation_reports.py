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
  exists;
- 422 with its reasons when it refuses the caller's data, as text or one
  per field as FastAPI writes them, and 400 with a code in
  ``CALLER_ROW_REFUSAL_CODES`` and its reason when a region, dataset or
  dynamic the caller named does not exist (the Public API checks the country
  and policies first): SimulationServiceRefusalError, with the code and
  reasons;
- 400 with any other code, or none: a state of the service rather than the
  caller's error, such as ``unknown_catalog_version`` while a release
  deploys, or a row the Public API already checked. The service is
  unavailable (SimulationServiceUnavailableError), with its code and reason;
- 500 (``internal_error``) when it failed, possibly after creating the
  record: SimulationServiceInternalError, with its code and reason;
- 503 with its code and reason when it cannot read its manifest or
  database, before creating anything: SimulationServiceUnavailableError,
  with the code and reason. When Modal refuses the run's call, the service
  has created the record and failed its run, and its 503 names the record
  (``report_id`` or ``simulation_id``): SimulationServiceUnavailableError,
  with the code, the reason and the record's ID;
- anything else: the service is unavailable
  (SimulationServiceUnavailableError), as it is for no answer, a 400 or 422
  that cannot be read, a gateway token that cannot be fetched and missing
  configuration. No answer means a connection never made (``ConnectError``,
  ``ConnectTimeout``, ``PoolTimeout``).

Some answers may follow a record the service created, so they are never
SimulationServiceUnavailableError, whose 503 says nothing was created. Each
is SimulationServiceAnswerUnreadableError: an answer lost once the request
may have been sent (a read timeout, a dropped connection); a 502 or 504 a
proxy in front of the service answers in its place; and a 503 that cannot be
read, which Cloud Run's front end also answers in the service's place, or
whose ``report_id`` or ``simulation_id`` is not a UUID, or that names a
record other than the submission's own, which shows the service wrote rows.
Their message, like the 500's, asks the caller to submit again, and says
that this creates a second record if the first request went through.

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
from typing import TYPE_CHECKING, Any, Literal, NoReturn
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
# The codes of the simulation service's 400 that name a row the caller chose
# and the Public API does not check: the region, the dataset, or a dynamic
# the catalog version its default worker runs does not have. Each is the
# caller's error and answers 422. Any other 400 is a state of the service,
# such as a catalog version missing while a release deploys, or a row the
# Public API already checked, and answers 503.
CALLER_ROW_REFUSAL_CODES = frozenset(
    {"unknown_region", "unknown_dataset", "unknown_dynamic"}
)
UNREACHABLE = "The simulation service could not be reached."
# The service never answers 502 or 504 itself: a proxy in front of it, such as
# Cloud Run's front end, answers them in its place, possibly after the
# service created the record. Cloud Run's front end also answers 503 in its
# place, which is why a 503 that cannot be read is treated the same way.
PROXY_STAND_IN_STATUSES = frozenset(
    {HTTPStatus.BAD_GATEWAY, HTTPStatus.GATEWAY_TIMEOUT}
)
# Transport errors raised before the request could reach the service. After
# any other, the service may have received the submission and created the
# record.
CONNECTION_NEVER_MADE = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


# What a submission creates.
RecordName = Literal["report", "simulation"]


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
    """A refusal's or failure's body: a reason, or each refused request field.

    It may also name its ``code``, and a 503 after Modal refused the run's
    call names the record the service created and failed.
    """

    detail: str | list[_RefusedField]
    code: str | None = None
    report_id: UUID | None = None
    simulation_id: UUID | None = None

    def created_record_id(self, record: RecordName) -> UUID | None:
        """Return the ID the body gives the submission's own record, if any."""
        return self.report_id if record == "report" else self.simulation_id

    def names_only_another_record(self, record: RecordName) -> bool:
        """Return whether the body names a record, but not the submission's own."""
        names_a_record = self.report_id is not None or self.simulation_id is not None
        return names_a_record and self.created_record_id(record) is None


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


def _refusal(answer: SimulationAnswer) -> _Refusal | None:
    try:
        return _Refusal.model_validate_json(answer.content)
    except ValidationError:
        return None


def _answer_lost(error: str, record: RecordName) -> str:
    """Ask the caller to submit the ``record`` again, which may create a second.

    The service may have created the record, but its answer does not say so;
    ``error`` says what arrived instead. No route finds a record by what it
    was submitted with, so the caller cannot check.
    """
    return (
        "The simulation service may have received the request, but its answer "
        f"was lost ({error}). Submit the {record} again; if the first request "
        f"went through, this creates a second {record}."
    )


def _status_code_and_reason(status_code: int, refusal: _Refusal | None) -> str:
    """Return ``status code: reason``, or ``status: reason`` without a code.

    When the body cannot be read, return ``an unreadable status``.
    """
    if refusal is None:
        return f"an unreadable {status_code}"
    code = "" if refusal.code is None else f" {refusal.code}"
    return f"{status_code}{code}: {_refusal_reason(refusal)}"


def _code_and_reason(refusal: _Refusal) -> str:
    """Return `` (code): reason``, or ``: reason`` when the service gave no code."""
    code = "" if refusal.code is None else f" ({refusal.code})"
    return f"{code}: {_refusal_reason(refusal)}"


def _raise_for_refused_request(
    answer: SimulationAnswer, refusal: _Refusal, record: RecordName
) -> NoReturn:
    """Raise the error the service's readable 400 or 422 means.

    A 422, or a 400 with a code in ``CALLER_ROW_REFUSAL_CODES``, is the
    caller's error. Any other 400 is the service's state, so it is
    unavailable.
    """
    code_and_reason = _code_and_reason(refusal)
    if (
        answer.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        or refusal.code in CALLER_ROW_REFUSAL_CODES
    ):
        msg = f"The simulation service cannot run this request{code_and_reason}"
        raise SimulationServiceRefusalError(msg)
    msg = f"The simulation service refused the {record}{code_and_reason}"
    raise SimulationServiceUnavailableError(msg)


def _raise_for_unavailable(
    answer: SimulationAnswer, refusal: _Refusal | None, record: RecordName
) -> NoReturn:
    """Raise the error the service's 503 means.

    A 503 that cannot be read, such as Cloud Run's own or one naming an ID
    that is not a UUID, and one naming only a record other than ``record``
    may follow a record the service created:
    SimulationServiceAnswerUnreadableError. Any other is the service's own
    unavailability, naming the ``record`` it created when it names one.
    """
    if refusal is None or refusal.names_only_another_record(record):
        msg = _answer_lost(_status_code_and_reason(answer.status_code, refusal), record)
        raise SimulationServiceAnswerUnreadableError(msg)
    created_record_id = refusal.created_record_id(record)
    if created_record_id is None:
        msg = f"The simulation service is unavailable{_code_and_reason(refusal)}"
        raise SimulationServiceUnavailableError(msg)
    msg = (
        f"The simulation service created {record} {created_record_id}, but is "
        f"unavailable{_code_and_reason(refusal)}"
    )
    raise SimulationServiceUnavailableError(msg, created_record_id=created_record_id)


def _raise_for_refusal(answer: SimulationAnswer, record: RecordName) -> None:
    """Raise the error a refusal, a failure or another answer means.

    ``record`` names what the submission creates.
    """
    refusal = _refusal(answer)
    if answer.status_code in REFUSAL_STATUSES:
        if refusal is None:
            msg = f"The simulation service answered {answer.status_code} unreadably."
            raise SimulationServiceUnavailableError(msg)
        _raise_for_refused_request(answer, refusal, record)
    if answer.status_code == HTTPStatus.INTERNAL_SERVER_ERROR:
        msg = _answer_lost(_status_code_and_reason(answer.status_code, refusal), record)
        raise SimulationServiceInternalError(msg)
    if answer.status_code in PROXY_STAND_IN_STATUSES:
        msg = _answer_lost(
            f"a proxy answered {answer.status_code} in its place", record
        )
        raise SimulationServiceAnswerUnreadableError(msg)
    if answer.status_code == HTTPStatus.SERVICE_UNAVAILABLE:
        _raise_for_unavailable(answer, refusal, record)
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
        *,
        record: RecordName,
    ) -> SimulationAnswer:
        """Send ``body`` and return the answer, which may be a refusal.

        Raise SimulationServiceUnavailableError when the connection was never
        made or the gateway token cannot be fetched, and
        SimulationServiceAnswerUnreadableError when the answer was lost after
        the submission may have reached the service, which may then have
        created the ``record``.
        """
        try:
            return send(self._http_client, body)
        except (*CONNECTION_NEVER_MADE, GatewayAuthError) as error:
            raise SimulationServiceUnavailableError(UNREACHABLE) from error
        except httpx.HTTPError as error:
            msg = _answer_lost(type(error).__name__, record)
            raise SimulationServiceAnswerUnreadableError(msg) from error

    def submit_simulation(
        self, simulation: EconomySimulationCreationInput
    ) -> SubmittedSimulation:
        """Create the simulation and its first run; return their IDs.

        Raise the errors ``SimulationServiceClient`` names.
        """
        answer = self._answer(
            self._send_simulation, simulation_request(simulation), record="simulation"
        )
        if answer.status_code not in CREATED_STATUSES:
            _raise_for_refusal(answer, "simulation")
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
        """Create the report, its simulations and runs; return the report's IDs.

        Raise the errors ``SimulationServiceClient`` names.
        """
        answer = self._answer(
            self._send_report, report_request(report), record="report"
        )
        if answer.status_code not in CREATED_STATUSES:
            _raise_for_refusal(answer, "report")
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
