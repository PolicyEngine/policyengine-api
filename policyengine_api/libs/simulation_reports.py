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
the year, the region code and the stored policy and dynamic (null for
current law). A report request names the country, ``report_type``
(``economy``), the label and description, the year and region its two
simulations share, each simulation's policy and dynamic, ``include_cliffs``,
and the SPM settings only when the caller gave them. No request names a
dataset: the simulation service calculates on the dataset its catalog
version gives the region. A budget window goes to the same
``POST /reports`` as ``report_type`` ``budget_window``, naming its first
year and ``budget_window_size`` in place of the year, and no
``include_cliffs``. A
household report goes there too, as ``report_type`` ``household``, naming
the label and description, the stored household, each simulation's policy
(the reform null for a report of the baseline alone), but no year: the
simulation service calculates the household's default year, adding every
variable the household lacks. None names a PolicyEngine.py version: the
simulation service runs its default worker's. The simulation service
answers:

- 201 or 202 with the created record's ID and its first run's ID: for a
  budget window, its budget-window run's ID (``budget_window_run_id``). One
  whose body cannot be read is SimulationServiceAnswerUnreadableError: the
  record exists;
- 422 with its reasons when it refuses the caller's data, as text or one
  per field as FastAPI writes them, and 400 with a code in
  ``CALLER_ROW_REFUSAL_CODES`` and its reason when a region, dataset or
  dynamic the caller named does not exist (the Public API checks the country
  and policies first): SimulationServiceInvalidRequestError, with the code
  and reasons;
- 400 with any other code, or none: a state of the service rather than the
  caller's error, such as ``unknown_catalog_version`` while a release
  deploys, or a row the Public API already checked. The service is
  unavailable (SimulationServiceUnavailableError), with its code and reason;
- 503 with its code when it cannot read its manifest or database, before
  creating anything: SimulationServiceUnavailableError, with the status and
  code. When Modal refuses the run's call, the service has created the
  record and failed its run, and its 503 names the record (``report_id`` or
  ``simulation_id``): SimulationServiceUnavailableError, with the status,
  the code and the record's ID;
- 401, 403, 404, 405, 413 or 429, which the gateway, Cloud Run or the
  service's framework answers before the service's route runs: the service
  is unavailable (SimulationServiceUnavailableError), with the status and
  code, as it is for no answer, a 400 or 422 that cannot be read, a gateway
  token that cannot be fetched and missing configuration. No answer means a
  connection never made (``ConnectError``, ``ConnectTimeout``,
  ``PoolTimeout``).

A readable 400's or 422's message gives the service's code, when it gave
one, and its reason, but not the service's status, since the route answers
with its own. A 422's reason, and a 400's with a code in
``CALLER_ROW_REFUSAL_CODES``, describes the caller's own request; any other
400's describes the service's state. A 500's or 503's ``detail`` may hold an
exception's text, which can carry stored data, so it never reaches the
caller. The message of a 500, a 503 or any status other than a readable 400
or 422 gives the service's status and code instead, such as
``503 modal_call_refused``, and gives the code only when it is a fixed
identifier (``FIXED_IDENTIFIER`` in
``policyengine_api.libs.simulation_service_answers``), which an exception's
text is not.

Some answers may follow a record the service created, so they are never
SimulationServiceUnavailableError, whose 503 says nothing was created:

- an answer lost once the request may have been sent (a read timeout, a
  dropped connection), and a 502 or 504 a proxy in front of the service
  answers in its place: SimulationServiceAnswerUnreadableError, saying the
  service may have received the request, but its answer was lost;
- 500 (``internal_error``) when the service failed, possibly after creating
  the record: SimulationServiceInternalError; a 503 that cannot be read,
  which Cloud Run's front end also answers in the service's place, or whose
  ``report_id`` or ``simulation_id`` is not a UUID, or that names a record
  other than the submission's own, which shows the service wrote rows; and
  any other status, which the service's route may answer after writing
  rows: SimulationServiceAnswerUnreadableError. Each says the service may
  have created the record, but failed, with the status and code.

Each of these asks the caller to submit again, and says that this creates a
second record if the first request went through.

The HTTP client, the sorting of transport errors, the refusal's reason, the
status and code a message gives, and the lost-answer and failure messages
come from ``policyengine_api.libs.simulation_service_answers``, which the
household calculation client shares.

``rerun_report`` runs a stored report again through the service's
``POST /reports/{report_id}/runs``; how it reads that route's answers is in
``policyengine_api.libs.simulation_report_reruns``.

Wiring the generated simulation client: ``post_simulation``,
``post_report`` and ``post_report_rerun`` are the only code that sends a
request, and each returns the status and body, which the rest of these
modules read. Once a
``policyengine-api-simulation-client`` release has the three routes, depend
on that release and make each function call the generated operation, as its
docstring says.
"""

from __future__ import annotations

from functools import lru_cache
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Literal, NoReturn, TypeVar
from uuid import UUID

from pydantic import ValidationError

from policyengine_api.libs.simulation_report_reruns import (
    post_report_rerun,
    start_report_rerun,
)
from policyengine_api.libs.simulation_service_answers import (
    CALLER_ROW_REFUSAL_CODES,
    CREATED_STATUSES,
    PROXY_STAND_IN_STATUSES,
    REFUSAL_STATUSES,
    SENT_BEFORE_ROUTE_STATUSES,
    AnswerModel,
    Refusal,
    SimulationAnswer,
    answer_lost,
    created_but_failed,
    fixed_identifier_code,
    parsed_body,
    refusal_reason,
    send_to_simulation_service,
    simulation_service_http_client,
    status_and_code,
    submit_again,
)
from policyengine_api.services.v2.simulation_service.types import (
    SimulationServiceAnswerUnreadableError,
    SimulationServiceInternalError,
    SimulationServiceInvalidRequestError,
    SimulationServiceUnavailableError,
    SubmittedBudgetWindow,
    SubmittedReport,
    SubmittedSimulation,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx

    from policyengine_api.services.v2.simulation_service.types import (
        BudgetWindowReportCreationInput,
        EconomyReportCreationInput,
        EconomySimulationCreationInput,
        HouseholdPolicyChoice,
        HouseholdReportCreationInput,
        PolicyChoice,
        ReportRerunInput,
    )

SIMULATIONS_PATH = "/simulations"
REPORTS_PATH = "/reports"


# What a submission creates.
RecordName = Literal["report", "simulation"]
# The simulation service's created answer a submission reads.
CreatedAnswerT = TypeVar("CreatedAnswerT", bound=AnswerModel)


class _CreatedSimulation(AnswerModel):
    simulation_id: UUID
    simulation_run_id: UUID


class _CreatedReport(AnswerModel):
    report_id: UUID
    report_run_id: UUID


class _CreatedBudgetWindow(AnswerModel):
    report_id: UUID
    budget_window_run_id: UUID


class _Refusal(Refusal):
    """A refusal's or failure's body: a reason, or each refused request field.

    It may also name its ``code``, and a 503 after Modal refused the run's
    call names the record the service created and failed. A 503 is the
    service's own only in this shape, but its reason is never passed on.
    """

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
        **_policy_choice(simulation),
    }


def _report_definition(
    report: EconomyReportCreationInput | BudgetWindowReportCreationInput,
) -> dict[str, Any]:
    """Return the request fields economy reports and budget windows both send.

    ``spm`` is sent only when the caller gave it.
    """
    body: dict[str, Any] = {
        "country": report.country_id,
        "report_type": report.kind,
        "label": report.label,
        "description": report.description,
        "year": report.year,
        "region_code": report.region_code,
        "baseline": _policy_choice(report.baseline),
        "reform": _policy_choice(report.reform),
    }
    if report.spm is not None:
        body["spm"] = report.spm.model_dump(mode="json")
    return body


def report_request(report: EconomyReportCreationInput) -> dict[str, Any]:
    """Return the simulation service's request body for the report.

    ``spm`` is sent only when the caller gave it.
    """
    return {**_report_definition(report), "include_cliffs": report.include_cliffs}


def budget_window_request(report: BudgetWindowReportCreationInput) -> dict[str, Any]:
    """Return the simulation service's request body for the budget window.

    ``year`` is the window's first year. ``spm`` is sent only when the
    caller gave it.
    """
    return {
        **_report_definition(report),
        "budget_window_size": report.budget_window_size,
    }


def _household_policy_choice(choice: HouseholdPolicyChoice) -> dict[str, str | None]:
    return {"policy_id": None if choice.policy_id is None else str(choice.policy_id)}


def household_report_request(report: HouseholdReportCreationInput) -> dict[str, Any]:
    """Return the simulation service's request body for the household report.

    ``reform`` is null for a report of the baseline alone.
    """
    return {
        "country": report.country_id,
        "report_type": report.kind,
        "label": report.label,
        "description": report.description,
        "household_id": str(report.household_id),
        "baseline": _household_policy_choice(report.baseline),
        "reform": (
            None if report.reform is None else _household_policy_choice(report.reform)
        ),
    }


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


def _refusal(answer: SimulationAnswer) -> _Refusal | None:
    try:
        return _Refusal.model_validate_json(answer.content)
    except ValidationError:
        return None


def _status_and_code(answer: SimulationAnswer) -> str:
    """Return the answer's status and code, such as ``503 modal_call_refused``.

    Return the status alone when the body is not a JSON object with a text
    code, or its code is not a fixed identifier, such as an empty code or an
    exception's text. Never the body's reason.
    """
    return status_and_code(
        answer.status_code, fixed_identifier_code(parsed_body(answer))
    )


def _submit_again(record: RecordName) -> str:
    """Ask the caller to submit the ``record`` again, which may create a second."""
    return submit_again(record, record)


def _failed_after_possible_creation(
    answer: SimulationAnswer, record: RecordName
) -> str:
    """Say the service may have created the ``record``, but failed.

    The message gives the answer's status and code, never its reason, which
    may be an exception's text.
    """
    return created_but_failed(record, _status_and_code(answer), _submit_again(record))


def _code_and_reason(refusal: _Refusal) -> str:
    """Return `` (code): reason``, or ``: reason`` when the service gave no code."""
    code = "" if refusal.code is None else f" ({refusal.code})"
    return f"{code}: {refusal_reason(refusal)}"


def _raise_for_refused_request(
    answer: SimulationAnswer, refusal: _Refusal, record: RecordName
) -> NoReturn:
    """Raise the error the service's readable 400 or 422 means.

    A 422, or a 400 with a code in ``CALLER_ROW_REFUSAL_CODES``, is the
    caller's error, and its reason describes the caller's own request. Any
    other 400 is the service's state, so it is unavailable, and its reason
    describes that state. Either message gives the service's code and
    reason, but not its status, since the route answers with its own.
    """
    code_and_reason = _code_and_reason(refusal)
    if (
        answer.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        or refusal.code in CALLER_ROW_REFUSAL_CODES
    ):
        msg = f"The simulation service cannot run this request{code_and_reason}"
        raise SimulationServiceInvalidRequestError(msg)
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
    Each message gives the status and code, never the reason.
    """
    if refusal is None or refusal.names_only_another_record(record):
        msg = _failed_after_possible_creation(answer, record)
        raise SimulationServiceAnswerUnreadableError(msg)
    status_and_code = _status_and_code(answer)
    created_record_id = refusal.created_record_id(record)
    if created_record_id is None:
        msg = f"The simulation service is unavailable ({status_and_code})."
        raise SimulationServiceUnavailableError(msg)
    msg = (
        f"The simulation service created {record} {created_record_id}, but is "
        f"unavailable ({status_and_code})."
    )
    raise SimulationServiceUnavailableError(msg, created_record_id=created_record_id)


def _raise_for_refusal(answer: SimulationAnswer, record: RecordName) -> NoReturn:
    """Raise the error a refusal, a failure or another answer means.

    ``record`` names what the submission creates. A status this module does
    not expect may follow rows the service's route wrote, unless it is one
    of ``SENT_BEFORE_ROUTE_STATUSES``.
    """
    status_code = answer.status_code
    if status_code in REFUSAL_STATUSES:
        refusal = _refusal(answer)
        if refusal is None:
            msg = f"The simulation service answered {status_code} unreadably."
            raise SimulationServiceUnavailableError(msg)
        _raise_for_refused_request(answer, refusal, record)
    if status_code in PROXY_STAND_IN_STATUSES:
        msg = answer_lost(
            f"a proxy answered {status_code} in its place", _submit_again(record)
        )
        raise SimulationServiceAnswerUnreadableError(msg)
    if status_code == HTTPStatus.SERVICE_UNAVAILABLE:
        _raise_for_unavailable(answer, _refusal(answer), record)
    if status_code in SENT_BEFORE_ROUTE_STATUSES:
        msg = f"The simulation service is unavailable ({_status_and_code(answer)})."
        raise SimulationServiceUnavailableError(msg)
    msg = _failed_after_possible_creation(answer, record)
    if status_code == HTTPStatus.INTERNAL_SERVER_ERROR:
        raise SimulationServiceInternalError(msg)
    raise SimulationServiceAnswerUnreadableError(msg)


class SimulationServiceReportClient:
    """Create simulations and reports, and run reports again, through the service."""

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
        send_report_rerun: Callable[
            [httpx.Client, UUID, dict[str, Any]], SimulationAnswer
        ] = post_report_rerun,
    ) -> None:
        """Send through ``send_simulation``, ``send_report`` and ``send_report_rerun``.

        Each sends on ``http_client``, which has the service's base URL.
        """
        self._http_client = http_client
        self._send_simulation = send_simulation
        self._send_report = send_report
        self._send_report_rerun = send_report_rerun

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
        return cls(simulation_service_http_client(transport=transport))

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
        return send_to_simulation_service(
            send, self._http_client, body, submit_again_sentence=_submit_again(record)
        )

    def _created(
        self,
        send: Callable[[httpx.Client, dict[str, Any]], SimulationAnswer],
        body: dict[str, Any],
        created_model: type[CreatedAnswerT],
        *,
        record: RecordName,
        created_name: str,
    ) -> CreatedAnswerT:
        """Send ``body`` and read the created answer as ``created_model``.

        ``record`` names what the submission creates, for the refusals and
        failures; ``created_name`` names it in the error for a created answer
        that cannot be read, since the record exists. Raise the errors
        ``SimulationServiceClient`` names.
        """
        answer = self._answer(send, body, record=record)
        if answer.status_code not in CREATED_STATUSES:
            _raise_for_refusal(answer, record)
        try:
            return created_model.model_validate_json(answer.content)
        except ValidationError as error:
            msg = (
                f"The simulation service created the {created_name}, but its "
                "answer could not be read."
            )
            raise SimulationServiceAnswerUnreadableError(msg) from error

    def submit_simulation(
        self, simulation: EconomySimulationCreationInput
    ) -> SubmittedSimulation:
        """Create the simulation and its first run; return their IDs.

        Raise the errors ``SimulationServiceClient`` names.
        """
        created = self._created(
            self._send_simulation,
            simulation_request(simulation),
            _CreatedSimulation,
            record="simulation",
            created_name="simulation",
        )
        return SubmittedSimulation(
            simulation_id=created.simulation_id,
            simulation_run_id=created.simulation_run_id,
        )

    def submit_report(self, report: EconomyReportCreationInput) -> SubmittedReport:
        """Create the report, its simulations and runs; return the report's IDs.

        Raise the errors ``SimulationServiceClient`` names.
        """
        created = self._created(
            self._send_report,
            report_request(report),
            _CreatedReport,
            record="report",
            created_name="report",
        )
        return SubmittedReport(
            report_id=created.report_id, report_run_id=created.report_run_id
        )

    def submit_household_report(
        self, report: HouseholdReportCreationInput
    ) -> SubmittedReport:
        """Create the household report, its simulations and runs; return its IDs.

        It is sent to the report route, so its refusals and failures are a
        report's. Raise the errors ``SimulationServiceClient`` names.
        """
        created = self._created(
            self._send_report,
            household_report_request(report),
            _CreatedReport,
            record="report",
            created_name="report",
        )
        return SubmittedReport(
            report_id=created.report_id, report_run_id=created.report_run_id
        )

    def submit_budget_window(
        self, report: BudgetWindowReportCreationInput
    ) -> SubmittedBudgetWindow:
        """Create the budget window, its simulations and runs; return its IDs.

        It is sent to the report route, so its refusals and failures are a
        report's. Raise the errors ``SimulationServiceClient`` names.
        """
        created = self._created(
            self._send_report,
            budget_window_request(report),
            _CreatedBudgetWindow,
            record="report",
            created_name="budget window",
        )
        return SubmittedBudgetWindow(
            report_id=created.report_id,
            budget_window_run_id=created.budget_window_run_id,
        )

    def rerun_report(self, rerun: ReportRerunInput) -> None:
        """Have the service create and start the stored report's new run.

        Raise the errors ``policyengine_api.libs.simulation_report_reruns``
        lists for the service's answers.
        """
        start_report_rerun(self._http_client, rerun, send=self._send_report_rerun)


@lru_cache(maxsize=1)
def process_simulation_service_client() -> SimulationServiceReportClient:
    """Return the process's client, built from the environment on first use.

    Its connections and gateway token are reused across requests. A
    configuration error is raised again on the next call, not kept.
    """
    return SimulationServiceReportClient.from_environment()
