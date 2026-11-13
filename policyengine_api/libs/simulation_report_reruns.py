"""Run a stored report again through the simulation service.

``start_report_rerun`` is what ``SimulationServiceReportClient.rerun_report``
does: it posts ``{"force": …}`` to the Cloud Run simulation service's
``POST /reports/{report_id}/runs``, through the same HTTP client as the
service's other v2 routes (``policyengine_api.libs.simulation_reports``).
The service creates the stored report's new run on its default worker's
versions and starts it, keeping every earlier run. Without ``force``, each
side reuses a run of its own simulation that succeeded on those versions.

The Public API reads the report in its country before asking, so it never
asks about a report it does not have. The simulation service answers:

- 201 or 202 naming the report: the new run exists. One whose body cannot
  be read, or that names another report, is
  SimulationServiceAnswerUnreadableError;
- 409 with ``code`` and ``detail`` when it will not run the report again
  now: ``run_in_progress``, naming the run pending or running in
  ``run_id``, or ``rerun_not_supported`` for a report it does not run again.
  SimulationServiceConflictError, with the code, reason and run. It answers
  409 before writing anything, so one that cannot be read is
  SimulationServiceUnavailableError;
- 422 with its reasons when the stored policies or dynamics cannot be
  calculated on the current catalog version, and 400 with a code in
  ``CALLER_ROW_REFUSAL_CODES`` when that catalog version lacks the region,
  dataset or a dynamic the report names: SimulationServiceInvalidRequestError,
  with the code and reasons. Any other 400 is the service's own state, such
  as a catalog version missing while a release deploys:
  SimulationServiceUnavailableError, with the code and reason;
- 503 with its code when it cannot answer now, before writing anything, and
  ``modal_call_refused`` naming the report and its new run (``run_id``) when
  Modal refused the run's call and the service failed the run: either is
  SimulationServiceUnavailableError, whose message gives the status and
  code, and names the failed run. Nothing is running, so running the report
  again later is safe;
- 401, 403, 404, 405, 413 or 429, sent before its route writes anything:
  SimulationServiceUnavailableError. A 404 is the service's state too, a
  route it does not have yet or a database it reads differently, since the
  Public API has just read the report.

Any other answer may follow a new run the service created, so it is never
SimulationServiceUnavailableError, whose 503 says nothing was started: an
answer lost after the request may have been sent and a proxy's 502 or 504
(SimulationServiceAnswerUnreadableError), a 500
(SimulationServiceInternalError), a 503 that cannot be read or names another
record, and any other status (SimulationServiceAnswerUnreadableError). Each
asks the caller to read the report to see whether it has a new run before
running it again. Running it again while that run is pending or running
answers 409, so a second request starts no second calculation.

As for a submission, a 400's or 422's or 409's message gives the service's
code and reason, but never its status, and any other message gives the
status and code, never the reason, which may be an exception's text.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Any, NoReturn
from uuid import UUID

from pydantic import ValidationError

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
    fixed_identifier_code,
    parsed_body,
    refusal_reason,
    send_to_simulation_service,
    status_and_code,
)
from policyengine_api.services.v2.simulation_service.types import (
    SimulationServiceAnswerUnreadableError,
    SimulationServiceConflictError,
    SimulationServiceInternalError,
    SimulationServiceInvalidRequestError,
    SimulationServiceUnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx

    from policyengine_api.services.v2.simulation_service.types import (
        ReportRerunInput,
    )

READ_BEFORE_RUNNING_AGAIN = (
    "Read the report to see whether it has a new run before running it again."
)
UNREADABLE_START = (
    "The simulation service answered that it started a new run of the report, "
    f"but its answer could not be read. {READ_BEFORE_RUNNING_AGAIN}"
)


class _RerunStarted(AnswerModel):
    report_id: UUID


class _RerunRefusal(Refusal):
    """A refusal's or failure's body: a reason, or each refused field.

    It may name its ``code``; a 409 for a run in progress names that run in
    ``run_id``, and a 503 after Modal refused the new run's call names the
    report and the run it failed.
    """

    code: str | None = None
    report_id: UUID | None = None
    simulation_id: UUID | None = None
    run_id: UUID | None = None


def report_runs_path(report_id: UUID) -> str:
    """Return the simulation service's path for the report's runs."""
    return f"/reports/{report_id}/runs"


def report_rerun_request(rerun: ReportRerunInput) -> dict[str, Any]:
    """Return the simulation service's request body for the re-run."""
    return {"force": rerun.force}


def post_report_rerun(
    http_client: httpx.Client, report_id: UUID, body: dict[str, Any]
) -> SimulationAnswer:
    """Send one re-run to the simulation service and return its answer.

    Raise httpx.HTTPError when no answer arrives, and GatewayAuthError when
    the gateway token cannot be fetched. ``http_client`` has the service's
    base URL. With the generated simulation client, this body becomes the
    route's operation (``rerun_report.sync_detailed`` with ``report_id`` and
    ``ReportRerunRequest.from_dict(body)``), as
    ``policyengine_api.libs.simulation_reports.post_report`` describes.
    """
    response = http_client.post(report_runs_path(report_id), json=body)
    return SimulationAnswer(status_code=response.status_code, content=response.content)


def _refusal(answer: SimulationAnswer) -> _RerunRefusal | None:
    try:
        return _RerunRefusal.model_validate_json(answer.content)
    except ValidationError:
        return None


def _status_and_code(answer: SimulationAnswer) -> str:
    """Return the answer's status and fixed-identifier code, never its reason."""
    return status_and_code(
        answer.status_code, fixed_identifier_code(parsed_body(answer))
    )


def _code_and_reason(refusal: _RerunRefusal) -> str:
    """Return `` (code): reason``, or ``: reason`` when the service gave no code."""
    code = "" if refusal.code is None else f" ({refusal.code})"
    return f"{code}: {refusal_reason(refusal)}"


def _possibly_started(answer: SimulationAnswer) -> str:
    """Say the service may have started a new run, but failed, and what to do."""
    return (
        "The simulation service may have started a new run of the report, but "
        f"it failed ({_status_and_code(answer)}). {READ_BEFORE_RUNNING_AGAIN}"
    )


def _raise_for_refused_request(
    answer: SimulationAnswer, refusal: _RerunRefusal
) -> NoReturn:
    """Raise the error a readable 400 or 422 means."""
    code_and_reason = _code_and_reason(refusal)
    if (
        answer.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        or refusal.code in CALLER_ROW_REFUSAL_CODES
    ):
        msg = f"The simulation service cannot run the report again{code_and_reason}"
        raise SimulationServiceInvalidRequestError(msg)
    msg = f"The simulation service refused to run the report again{code_and_reason}"
    raise SimulationServiceUnavailableError(msg)


def _raise_for_conflict(answer: SimulationAnswer) -> NoReturn:
    """Raise the error a 409 means: a conflict, or unavailable when unreadable."""
    refusal = _refusal(answer)
    if refusal is None or refusal.code is None:
        msg = f"The simulation service answered {answer.status_code} unreadably."
        raise SimulationServiceUnavailableError(msg)
    msg = (
        "The simulation service will not run the report again now"
        f"{_code_and_reason(refusal)}"
    )
    raise SimulationServiceConflictError(msg, run_id=refusal.run_id)


def _raise_for_unavailable(answer: SimulationAnswer, report_id: UUID) -> NoReturn:
    """Raise the error a 503 means.

    One naming this report says the service started its new run and failed
    it; one naming no record says the service wrote nothing. One that cannot
    be read, such as Cloud Run's own, or naming another record, may follow a
    new run the service created.
    """
    refusal = _refusal(answer)
    if (
        refusal is None
        or refusal.simulation_id is not None
        or refusal.report_id not in {None, report_id}
    ):
        raise SimulationServiceAnswerUnreadableError(_possibly_started(answer))
    unavailable = f"is unavailable ({_status_and_code(answer)})"
    if refusal.report_id is None:
        msg = f"The simulation service {unavailable}."
        raise SimulationServiceUnavailableError(msg)
    new_run = "a new run" if refusal.run_id is None else f"run {refusal.run_id}"
    msg = (
        f"The simulation service started {new_run} of report {report_id}, then "
        f"failed it, and {unavailable}. Run the report again later."
    )
    raise SimulationServiceUnavailableError(msg)


def _raise_for_refusal(answer: SimulationAnswer, report_id: UUID) -> NoReturn:
    """Raise the error any answer but a started re-run means."""
    status_code = answer.status_code
    if status_code in REFUSAL_STATUSES:
        refusal = _refusal(answer)
        if refusal is None:
            msg = f"The simulation service answered {status_code} unreadably."
            raise SimulationServiceUnavailableError(msg)
        _raise_for_refused_request(answer, refusal)
    if status_code == HTTPStatus.CONFLICT:
        _raise_for_conflict(answer)
    if status_code in PROXY_STAND_IN_STATUSES:
        msg = answer_lost(
            f"a proxy answered {status_code} in its place", READ_BEFORE_RUNNING_AGAIN
        )
        raise SimulationServiceAnswerUnreadableError(msg)
    if status_code == HTTPStatus.SERVICE_UNAVAILABLE:
        _raise_for_unavailable(answer, report_id)
    if status_code in SENT_BEFORE_ROUTE_STATUSES:
        msg = f"The simulation service is unavailable ({_status_and_code(answer)})."
        raise SimulationServiceUnavailableError(msg)
    if status_code == HTTPStatus.INTERNAL_SERVER_ERROR:
        raise SimulationServiceInternalError(_possibly_started(answer))
    raise SimulationServiceAnswerUnreadableError(_possibly_started(answer))


def _require_started(answer: SimulationAnswer, report_id: UUID) -> None:
    """Raise unless the started answer can be read and names the report."""
    try:
        started = _RerunStarted.model_validate_json(answer.content)
    except ValidationError as error:
        raise SimulationServiceAnswerUnreadableError(UNREADABLE_START) from error
    if started.report_id != report_id:
        raise SimulationServiceAnswerUnreadableError(UNREADABLE_START)


def start_report_rerun(
    http_client: httpx.Client,
    rerun: ReportRerunInput,
    *,
    send: Callable[[httpx.Client, UUID, dict[str, Any]], SimulationAnswer],
) -> None:
    """Have the simulation service create and start the report's new run.

    Send through ``send`` on ``http_client``, and raise the errors the module
    docstring lists for the service's answers. A connection never made, or a
    gateway token that cannot be fetched, is
    SimulationServiceUnavailableError.
    """
    answer = send_to_simulation_service(
        lambda client, body: send(client, rerun.report_id, body),
        http_client,
        report_rerun_request(rerun),
        submit_again_sentence=READ_BEFORE_RUNNING_AGAIN,
    )
    if answer.status_code in CREATED_STATUSES:
        _require_started(answer, rerun.report_id)
        return
    _raise_for_refusal(answer, rerun.report_id)
