"""Run a stored report again through the simulation service; read its answers."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import httpx
import pytest

from policyengine_api.fastapi_routes.v2.reports.routes import REPORT_ERROR_MAPPINGS
from policyengine_api.libs.simulation_report_reruns import report_runs_path
from policyengine_api.libs.simulation_reports import SimulationServiceReportClient
from policyengine_api.libs.simulation_service_answers import SimulationAnswer
from policyengine_api.services.v2.simulation_service.types import (
    ReportRerunInput,
    SimulationServiceAnswerUnreadableError,
    SimulationServiceConflictError,
    SimulationServiceInternalError,
    SimulationServiceInvalidRequestError,
    SimulationServiceUnavailableError,
)

SIMULATION_URL = "https://simulation.example.test"
ENVIRONMENT_VARIABLES = (
    "GATEWAY_AUTH_ISSUER",
    "GATEWAY_AUTH_AUDIENCE",
    "GATEWAY_AUTH_CLIENT_ID",
    "GATEWAY_AUTH_CLIENT_SECRET",
    "GATEWAY_AUTH_CLIENT_SECRET_RESOURCE",
    "GATEWAY_AUTH_REQUIRED",
    "SIM_ENTRYPOINT",
    "OLD_SIMULATION_GATEWAY_URL",
    "SIMULATION_ENTRYPOINT_URL",
)
REPORT_ID = UUID("00000000-0000-0000-0000-00000000d001")
OTHER_REPORT_ID = UUID("00000000-0000-0000-0000-00000000d002")
NEW_RUN_ID = UUID("00000000-0000-0000-0000-00000000d003")
RUNNING_RUN_ID = UUID("00000000-0000-0000-0000-00000000d004")
POLICY_ID = UUID("00000000-0000-0000-0000-00000000d005")
SIMULATION_ID = UUID("00000000-0000-0000-0000-00000000d006")
# What the simulation service answers once it has started the report's new run.
RERUN_STARTED = {
    "report_id": str(REPORT_ID),
    "report_run_id": str(NEW_RUN_ID),
    "status": "pending",
    "baseline_simulation_id": "00000000-0000-0000-0000-00000000d007",
    "baseline_simulation_run_id": "00000000-0000-0000-0000-00000000d008",
    "baseline_reused": True,
    "reform_simulation_id": "00000000-0000-0000-0000-00000000d009",
    "reform_simulation_run_id": "00000000-0000-0000-0000-00000000d00a",
    "reform_reused": False,
}
READ_BEFORE_RUNNING_AGAIN = (
    "Read the report to see whether it has a new run before running it again."
)


@pytest.fixture(autouse=True)
def configured_simulation_service(monkeypatch):
    """Name the Cloud Run simulation service; set no gateway credentials."""
    for name in ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SIMULATION_ENTRYPOINT_URL", f"{SIMULATION_URL}/")
    monkeypatch.setenv("SIM_ENTRYPOINT", "old_gateway_direct")
    monkeypatch.setenv("OLD_SIMULATION_GATEWAY_URL", "https://old.example.test")


def rerun_input(**changes: Any) -> ReportRerunInput:
    values: dict[str, Any] = {
        "country_id": "us",
        "report_id": REPORT_ID,
        "kind": "economy",
        "force": False,
        "policy_ids": (None, POLICY_ID),
    }
    return ReportRerunInput(**{**values, **changes})


def route_status(error: Exception) -> int:
    """Return the status the report routes answer ``error`` with."""
    return next(
        mapping.status_code
        for mapping in REPORT_ERROR_MAPPINGS
        if isinstance(error, mapping.error_types)
    )


class ScriptedService:
    """The simulation service, answering every request with one scripted answer."""

    def __init__(self, status_code: int = 201, body: object = RERUN_STARTED) -> None:
        self.status_code = status_code
        self.body = body
        self.requests: list[httpx.Request] = []

    def answer(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.body, bytes):
            return httpx.Response(self.status_code, content=self.body)
        return httpx.Response(self.status_code, json=self.body)

    def rerun(self, **changes: Any) -> None:
        client = SimulationServiceReportClient.from_environment(
            transport=httpx.MockTransport(self.answer)
        )
        client.rerun_report(rerun_input(**changes))


def possibly_started_message(status_and_code: str) -> str:
    return (
        "The simulation service may have started a new run of the report, but it "
        f"failed ({status_and_code}). {READ_BEFORE_RUNNING_AGAIN}"
    )


@pytest.mark.parametrize("force", [False, True])
def test_a_rerun_posts_force_to_the_reports_runs_route(
    force: bool,  # noqa: FBT001  # pytest passes parameters positionally
) -> None:
    service = ScriptedService()

    service.rerun(force=force)

    (request,) = service.requests
    assert request.method == "POST"
    assert str(request.url) == f"{SIMULATION_URL}/reports/{REPORT_ID}/runs"
    assert report_runs_path(REPORT_ID) == f"/reports/{REPORT_ID}/runs"
    assert json.loads(request.content) == {"force": force}


@pytest.mark.parametrize("status_code", [201, 202])
def test_a_started_rerun_naming_the_report_is_accepted(status_code: int) -> None:
    service = ScriptedService(
        status_code=status_code, body={"report_id": str(REPORT_ID)}
    )

    service.rerun()

    assert len(service.requests) == 1


@pytest.mark.parametrize(
    "body",
    [
        {**RERUN_STARTED, "report_id": str(OTHER_REPORT_ID)},
        {"report_run_id": str(NEW_RUN_ID)},
        b"not json",
    ],
    ids=["another-report", "no-report", "not-json"],
)
def test_a_started_answer_that_cannot_be_read_may_have_started_a_run(
    body: object,
) -> None:
    with pytest.raises(SimulationServiceAnswerUnreadableError) as unreadable:
        ScriptedService(body=body).rerun()

    assert route_status(unreadable.value) == 502
    assert str(unreadable.value) == (
        "The simulation service answered that it started a new run of the "
        f"report, but its answer could not be read. {READ_BEFORE_RUNNING_AGAIN}"
    )


def test_a_run_in_progress_is_a_conflict_naming_that_run() -> None:
    service = ScriptedService(
        status_code=409,
        body={
            "code": "run_in_progress",
            "detail": f"Report {REPORT_ID} has run {RUNNING_RUN_ID} running.",
            "run_id": str(RUNNING_RUN_ID),
        },
    )

    with pytest.raises(SimulationServiceConflictError) as conflict:
        service.rerun()

    assert conflict.value.run_id == RUNNING_RUN_ID
    assert str(conflict.value) == (
        "The simulation service will not run the report again now "
        f"(run_in_progress): Report {REPORT_ID} has run {RUNNING_RUN_ID} running."
    )


def test_a_report_the_service_does_not_run_again_is_a_conflict() -> None:
    service = ScriptedService(
        status_code=409,
        body={"code": "rerun_not_supported", "detail": "The report has no dataset."},
    )

    with pytest.raises(SimulationServiceConflictError) as conflict:
        service.rerun()

    assert conflict.value.run_id is None
    assert str(conflict.value) == (
        "The simulation service will not run the report again now "
        "(rerun_not_supported): The report has no dataset."
    )


@pytest.mark.parametrize(
    "body",
    [b"<html>conflict</html>", {"detail": 3}, {"code": "run_in_progress"}],
    ids=["not-json", "no-reason", "code-only"],
)
def test_a_conflict_that_cannot_be_read_is_unavailable(body: object) -> None:
    # The service answers 409 only before writing anything.
    with pytest.raises(SimulationServiceUnavailableError) as unavailable:
        ScriptedService(status_code=409, body=body).rerun()

    assert route_status(unavailable.value) == 503
    assert str(unavailable.value) == "The simulation service answered 409 unreadably."


def test_stored_values_the_service_cannot_calculate_are_refused_with_its_reasons() -> (
    None
):
    service = ScriptedService(
        status_code=422,
        body={
            "code": "missing_parameters",
            "detail": [
                {
                    "loc": ["report", "reform", "policy_id", "gov.example.amount"],
                    "msg": "The catalog version has no parameter gov.example.amount",
                }
            ],
        },
    )

    with pytest.raises(SimulationServiceInvalidRequestError) as refused:
        service.rerun()

    assert route_status(refused.value) == 422
    assert str(refused.value) == (
        "The simulation service cannot run the report again (missing_parameters): "
        "report.reform.policy_id.gov.example.amount: The catalog version has no "
        "parameter gov.example.amount"
    )


@pytest.mark.parametrize(
    "code", ["unknown_region", "unknown_dataset", "unknown_dynamic"]
)
def test_a_stored_row_the_catalog_version_lacks_is_refused(code: str) -> None:
    service = ScriptedService(
        status_code=400,
        body={
            "code": code,
            "detail": "The catalog version lacks a row the report names.",
        },
    )

    with pytest.raises(SimulationServiceInvalidRequestError) as refused:
        service.rerun()

    assert route_status(refused.value) == 422
    assert str(refused.value) == (
        f"The simulation service cannot run the report again ({code}): The "
        "catalog version lacks a row the report names."
    )


def test_a_400_about_the_services_own_state_is_unavailable() -> None:
    service = ScriptedService(
        status_code=400,
        body={
            "code": "unknown_catalog_version",
            "detail": "No catalog version for .py 4.3.0.",
        },
    )

    with pytest.raises(SimulationServiceUnavailableError) as unavailable:
        service.rerun()

    assert route_status(unavailable.value) == 503
    assert unavailable.value.created_record_id is None
    assert str(unavailable.value) == (
        "The simulation service refused to run the report again "
        "(unknown_catalog_version): No catalog version for .py 4.3.0."
    )


@pytest.mark.parametrize("status_code", [400, 422])
def test_a_refusal_that_cannot_be_read_is_unavailable(status_code: int) -> None:
    with pytest.raises(SimulationServiceUnavailableError) as unavailable:
        ScriptedService(status_code=status_code, body=b"refused").rerun()

    assert str(unavailable.value) == (
        f"The simulation service answered {status_code} unreadably."
    )


@pytest.mark.parametrize(
    ("status_code", "body", "status_and_code"),
    [
        (
            404,
            {"code": "unknown_report", "detail": "No such report."},
            "404 unknown_report",
        ),
        (404, {"detail": "Not Found"}, "404"),
        (401, b"", "401"),
        (403, {"code": "forbidden", "detail": "No permission."}, "403 forbidden"),
        (405, b"", "405"),
        (413, b"", "413"),
        (429, b"", "429"),
    ],
    ids=["unknown-report", "no-route", "401", "403", "405", "413", "429"],
)
def test_a_status_sent_before_the_service_writes_is_unavailable(
    status_code: int, body: object, status_and_code: str
) -> None:
    # The Public API has just read the report itself, so the service's 404 is
    # its own state: a route it does not have yet, or a database it cannot read.
    with pytest.raises(SimulationServiceUnavailableError) as unavailable:
        ScriptedService(status_code=status_code, body=body).rerun()

    assert route_status(unavailable.value) == 503
    assert str(unavailable.value) == (
        f"The simulation service is unavailable ({status_and_code})."
    )


def test_the_services_unavailability_is_passed_on_with_its_code_not_its_reason() -> (
    None
):
    service = ScriptedService(
        status_code=503,
        body={"code": "manifest_unavailable", "detail": "secret text"},
    )

    with pytest.raises(SimulationServiceUnavailableError) as unavailable:
        service.rerun()

    assert route_status(unavailable.value) == 503
    assert str(unavailable.value) == (
        "The simulation service is unavailable (503 manifest_unavailable)."
    )


def test_a_new_run_the_unavailable_service_failed_is_named() -> None:
    service = ScriptedService(
        status_code=503,
        body={
            "code": "modal_call_refused",
            "detail": "secret text",
            "report_id": str(REPORT_ID),
            "run_id": str(NEW_RUN_ID),
        },
    )

    with pytest.raises(SimulationServiceUnavailableError) as unavailable:
        service.rerun()

    assert route_status(unavailable.value) == 503
    assert str(unavailable.value) == (
        f"The simulation service started run {NEW_RUN_ID} of report {REPORT_ID}, "
        "then failed it, and is unavailable (503 modal_call_refused). Run the "
        "report again later."
    )


def test_a_failed_new_run_the_503_does_not_name_is_still_the_reports() -> None:
    service = ScriptedService(
        status_code=503,
        body={
            "code": "modal_call_refused",
            "detail": "secret text",
            "report_id": str(REPORT_ID),
        },
    )

    with pytest.raises(SimulationServiceUnavailableError) as unavailable:
        service.rerun()

    assert str(unavailable.value) == (
        f"The simulation service started a new run of report {REPORT_ID}, then "
        "failed it, and is unavailable (503 modal_call_refused). Run the report "
        "again later."
    )


@pytest.mark.parametrize(
    ("body", "status_and_code"),
    [
        (b"<html>Service Unavailable</html>", "503"),
        (
            {
                "code": "modal_call_refused",
                "detail": "x",
                "report_id": str(OTHER_REPORT_ID),
            },
            "503 modal_call_refused",
        ),
        (
            {
                "code": "modal_call_refused",
                "detail": "x",
                "simulation_id": str(SIMULATION_ID),
            },
            "503 modal_call_refused",
        ),
        (
            {"code": "modal_call_refused", "detail": "x", "report_id": "not-a-uuid"},
            "503 modal_call_refused",
        ),
    ],
    ids=["not-json", "another-report", "a-simulation", "malformed-id"],
)
def test_a_503_that_cannot_be_read_or_names_another_record_may_have_started_a_run(
    body: object, status_and_code: str
) -> None:
    with pytest.raises(SimulationServiceAnswerUnreadableError) as unreadable:
        ScriptedService(status_code=503, body=body).rerun()

    assert route_status(unreadable.value) == 502
    assert str(unreadable.value) == possibly_started_message(status_and_code)


def test_an_internal_error_may_have_started_a_run() -> None:
    service = ScriptedService(
        status_code=500, body={"code": "internal_error", "detail": "secret text"}
    )

    with pytest.raises(SimulationServiceInternalError) as failed:
        service.rerun()

    assert route_status(failed.value) == 502
    assert str(failed.value) == possibly_started_message("500 internal_error")


@pytest.mark.parametrize(
    ("status_code", "status_and_code"),
    [(200, "200"), (204, "204"), (302, "302"), (418, "418")],
)
def test_an_unexpected_status_may_have_started_a_run(
    status_code: int, status_and_code: str
) -> None:
    with pytest.raises(SimulationServiceAnswerUnreadableError) as unreadable:
        ScriptedService(status_code=status_code, body=b"").rerun()

    assert route_status(unreadable.value) == 502
    assert str(unreadable.value) == possibly_started_message(status_and_code)


@pytest.mark.parametrize("status_code", [502, 504])
def test_a_proxys_answer_in_place_of_the_services_may_have_started_a_run(
    status_code: int,
) -> None:
    with pytest.raises(SimulationServiceAnswerUnreadableError) as lost:
        ScriptedService(status_code=status_code, body=b"bad gateway").rerun()

    assert route_status(lost.value) == 502
    assert str(lost.value) == (
        "The simulation service may have received the request, but its answer "
        f"was lost (a proxy answered {status_code} in its place). "
        f"{READ_BEFORE_RUNNING_AGAIN}"
    )


def _client_raising(
    error_type: type[httpx.TransportError],
) -> SimulationServiceReportClient:
    def fail(request: httpx.Request) -> httpx.Response:
        msg = "the transport failed"
        raise error_type(msg, request=request)

    return SimulationServiceReportClient.from_environment(
        transport=httpx.MockTransport(fail)
    )


@pytest.mark.parametrize(
    "error_type", [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout]
)
def test_a_connection_never_made_is_unavailable(
    error_type: type[httpx.TransportError],
) -> None:
    with pytest.raises(
        SimulationServiceUnavailableError, match="could not be reached"
    ) as unavailable:
        _client_raising(error_type).rerun_report(rerun_input())

    assert route_status(unavailable.value) == 503


@pytest.mark.parametrize(
    "error_type", [httpx.ReadTimeout, httpx.ReadError, httpx.RemoteProtocolError]
)
def test_an_answer_lost_after_sending_may_have_started_a_run(
    error_type: type[httpx.TransportError],
) -> None:
    with pytest.raises(SimulationServiceAnswerUnreadableError) as lost:
        _client_raising(error_type).rerun_report(rerun_input())

    assert route_status(lost.value) == 502
    assert str(lost.value) == (
        "The simulation service may have received the request, but its answer "
        f"was lost ({error_type.__name__}). {READ_BEFORE_RUNNING_AGAIN}"
    )


def test_a_rerun_is_sent_through_its_one_replaceable_send_function() -> None:
    sent: list[tuple[UUID, dict[str, Any]]] = []

    def send_rerun(
        http_client: httpx.Client, report_id: UUID, body: dict[str, Any]
    ) -> SimulationAnswer:
        assert str(http_client.base_url).rstrip("/") == SIMULATION_URL
        sent.append((report_id, body))
        return SimulationAnswer(
            status_code=201, content=json.dumps(RERUN_STARTED).encode()
        )

    client = SimulationServiceReportClient(
        httpx.Client(base_url=SIMULATION_URL), send_report_rerun=send_rerun
    )

    client.rerun_report(rerun_input(force=True))

    assert sent == [(REPORT_ID, {"force": True})]
