"""Create simulations and reports through the simulation service; read its answers."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import httpx
import pytest

from policyengine_api.fastapi_routes.v2.reports.routes import REPORT_ERROR_MAPPINGS
from policyengine_api.fastapi_routes.v2.simulations.routes import (
    SIMULATION_ERROR_MAPPINGS,
)
from policyengine_api.libs.gateway_auth import GatewayAuthError
from policyengine_api.libs.simulation_reports import (
    REPORTS_PATH,
    SIMULATIONS_PATH,
    SimulationServiceReportClient,
)
from policyengine_api.libs.simulation_service_answers import SimulationAnswer
from policyengine_api.services.v2.simulation_service.types import (
    EconomyReportCreationInput,
    EconomySimulationCreationInput,
    SimulationServiceAnswerUnreadableError,
    SimulationServiceInternalError,
    SimulationServiceInvalidRequestError,
    SimulationServiceUnavailableError,
    SubmittedReport,
    SubmittedSimulation,
)
from policyengine_api.spm import SPMSelection
from tests.unit.v2.simulation_service_messages import (
    answer_lost_message,
    possibly_created_message,
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
REPORT_ID = UUID("00000000-0000-0000-0000-00000000b001")
REPORT_RUN_ID = UUID("00000000-0000-0000-0000-00000000b002")
SIMULATION_ID = UUID("00000000-0000-0000-0000-00000000b003")
SIMULATION_RUN_ID = UUID("00000000-0000-0000-0000-00000000b004")
POLICY_ID = UUID("00000000-0000-0000-0000-00000000b005")
DYNAMIC_ID = UUID("00000000-0000-0000-0000-00000000b006")
REPORT_CREATED = {
    "report_id": str(REPORT_ID),
    "report_run_id": str(REPORT_RUN_ID),
    "status": "pending",
}
SIMULATION_CREATED = {
    "simulation_id": str(SIMULATION_ID),
    "simulation_run_id": str(SIMULATION_RUN_ID),
    "status": "pending",
}


@pytest.fixture(autouse=True)
def configured_simulation_service(monkeypatch):
    """Name the Cloud Run simulation service; set no gateway credentials."""
    for name in ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SIMULATION_ENTRYPOINT_URL", f"{SIMULATION_URL}/")
    # The report routes exist only on the Cloud Run simulation service,
    # whatever the v1 economy routes select.
    monkeypatch.setenv("SIM_ENTRYPOINT", "old_gateway_direct")
    monkeypatch.setenv("OLD_SIMULATION_GATEWAY_URL", "https://old.example.test")


def report_input(**changes: Any) -> EconomyReportCreationInput:
    values: dict[str, Any] = {
        "country_id": "us",
        "kind": "economy",
        "label": "Expanded child tax credit",
        "year": 2026,
        "region_code": "state/ca",
        "baseline": {},
        "reform": {"policy_id": str(POLICY_ID)},
    }
    return EconomyReportCreationInput.model_validate({**values, **changes})


def simulation_input(**changes: Any) -> EconomySimulationCreationInput:
    values: dict[str, Any] = {
        "country_id": "uk",
        "kind": "economy",
        "year": 2027,
        "region_code": "country/wales",
        "policy_id": str(POLICY_ID),
    }
    return EconomySimulationCreationInput.model_validate({**values, **changes})


def _report_route_status(error: Exception) -> int:
    """Return the status the report route answers ``error`` with."""
    return next(
        mapping.status_code
        for mapping in REPORT_ERROR_MAPPINGS
        if isinstance(error, mapping.error_types)
    )


def _simulation_route_status(error: Exception) -> int:
    """Return the status the simulation route answers ``error`` with."""
    return next(
        mapping.status_code
        for mapping in SIMULATION_ERROR_MAPPINGS
        if isinstance(error, mapping.error_types)
    )


def submit_report(client: SimulationServiceReportClient) -> object:
    return client.submit_report(report_input())


def submit_simulation(client: SimulationServiceReportClient) -> object:
    return client.submit_simulation(simulation_input())


# The field naming each record in the simulation service's answers, and the
# record's ID in these tests.
CREATED_RECORD_IDS = {
    "report": ("report_id", REPORT_ID),
    "simulation": ("simulation_id", SIMULATION_ID),
}
# The field and ID of a record other than the submission's own.
OTHER_RECORD_IDS = {
    "report": ("simulation_id", SIMULATION_ID),
    "simulation": ("report_id", REPORT_ID),
}


# Each submission, the record it creates and the status its route answers with.
SUBMISSIONS = [
    pytest.param(submit_report, "report", _report_route_status, id="report"),
    pytest.param(
        submit_simulation, "simulation", _simulation_route_status, id="simulation"
    ),
]


class RecordingService:
    """The simulation service, answering every request with one scripted answer."""

    def __init__(self, status_code: int = 201, body: object = REPORT_CREATED) -> None:
        self.status_code = status_code
        self.body = body
        self.requests: list[httpx.Request] = []

    def answer(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.body, bytes):
            return httpx.Response(self.status_code, content=self.body)
        return httpx.Response(self.status_code, json=self.body)

    def client(self) -> SimulationServiceReportClient:
        return SimulationServiceReportClient.from_environment(
            transport=httpx.MockTransport(self.answer)
        )

    def sent_body(self) -> dict[str, object]:
        (request,) = self.requests
        return json.loads(request.content)


def test_a_report_is_posted_and_the_created_report_returned() -> None:
    service = RecordingService()

    submitted = service.client().submit_report(report_input())

    assert submitted == SubmittedReport(
        report_id=REPORT_ID, report_run_id=REPORT_RUN_ID
    )
    (request,) = service.requests
    assert request.method == "POST"
    assert str(request.url) == f"{SIMULATION_URL}{REPORTS_PATH}"
    assert service.sent_body() == {
        "country": "us",
        "report_type": "economy",
        "label": "Expanded child tax credit",
        "description": None,
        "year": 2026,
        "region_code": "state/ca",
        "baseline": {"policy_id": None, "dynamic_id": None},
        "reform": {"policy_id": str(POLICY_ID), "dynamic_id": None},
        "include_cliffs": False,
    }


def test_a_report_sends_its_options_and_spm_settings_only_when_given() -> None:
    service = RecordingService()

    service.client().submit_report(
        report_input(
            include_cliffs=True,
            description="Doubles the credit",
            reform={"policy_id": str(POLICY_ID), "dynamic_id": str(DYNAMIC_ID)},
            spm={"geography_kind": "national"},
        )
    )

    body = service.sent_body()
    assert body["include_cliffs"] is True
    assert body["description"] == "Doubles the credit"
    assert body["reform"] == {
        "policy_id": str(POLICY_ID),
        "dynamic_id": str(DYNAMIC_ID),
    }
    assert body["spm"] == SPMSelection(geography_kind="national").model_dump(
        mode="json"
    )


def test_a_simulation_is_posted_and_the_created_simulation_returned() -> None:
    service = RecordingService(status_code=202, body=SIMULATION_CREATED)

    submitted = service.client().submit_simulation(simulation_input())

    assert submitted == SubmittedSimulation(
        simulation_id=SIMULATION_ID, simulation_run_id=SIMULATION_RUN_ID
    )
    (request,) = service.requests
    assert str(request.url) == f"{SIMULATION_URL}{SIMULATIONS_PATH}"
    assert service.sent_body() == {
        "country": "uk",
        "simulation_type": "economy",
        "year": 2027,
        "region_code": "country/wales",
        "policy_id": str(POLICY_ID),
        "dynamic_id": None,
    }


def test_an_answer_with_fields_the_public_api_does_not_read_is_accepted() -> None:
    service = RecordingService(body={**REPORT_CREATED, "modal_call_id": "fc-1"})

    assert service.client().submit_report(report_input()).report_id == REPORT_ID


def test_data_the_service_refuses_is_reported_with_its_reason() -> None:
    service = RecordingService(
        status_code=422, body={"detail": "spm settings apply only to the US"}
    )

    with pytest.raises(SimulationServiceInvalidRequestError) as refused:
        service.client().submit_report(report_input())

    assert str(refused.value) == (
        "The simulation service cannot run this request: "
        "spm settings apply only to the US"
    )


def test_request_fields_the_service_refuses_are_reported_one_by_one() -> None:
    service = RecordingService(
        status_code=422,
        body={
            "detail": [
                {"loc": ["body", "year"], "msg": "too late", "type": "value_error"},
                {"loc": ["body", "reform", "policy_id"], "msg": "bad", "type": "x"},
            ]
        },
    )

    with pytest.raises(SimulationServiceInvalidRequestError) as refused:
        service.client().submit_report(report_input())

    assert str(refused.value) == (
        "The simulation service cannot run this request: "
        "year: too late; reform.policy_id: bad"
    )


def test_a_refusal_names_the_services_code_when_it_gives_one() -> None:
    service = RecordingService(
        status_code=422,
        body={
            "code": "spm_unsupported",
            "detail": "spm settings apply only to the US",
        },
    )

    with pytest.raises(SimulationServiceInvalidRequestError) as refused:
        service.client().submit_report(report_input())

    assert str(refused.value) == (
        "The simulation service cannot run this request (spm_unsupported): "
        "spm settings apply only to the US"
    )


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        ("unknown_region", "Region state/zz is not in the catalog version."),
        ("unknown_dataset", "Dataset cps_1999 is not in the catalog version."),
        ("unknown_dynamic", f"Dynamic {DYNAMIC_ID} is not stored in the country."),
    ],
    ids=["region", "dataset", "dynamic"],
)
@pytest.mark.parametrize(("submit", "record", "route_status"), SUBMISSIONS)
def test_a_row_the_caller_named_that_the_service_cannot_find_is_refused(
    submit, record: str, route_status, code: str, reason: str
) -> None:
    # The Public API does not check regions, datasets or dynamics: the caller
    # named one the simulation service's catalog version does not have.
    service = RecordingService(status_code=400, body={"code": code, "detail": reason})

    with pytest.raises(SimulationServiceInvalidRequestError) as refused:
        submit(service.client())

    assert route_status(refused.value) == 422
    assert str(refused.value) == (
        f"The simulation service cannot run this request ({code}): {reason}"
    )


@pytest.mark.parametrize(
    ("body", "stated_code"),
    [
        pytest.param(
            {
                "code": "unknown_catalog_version",
                "detail": "Country us has no catalog version for .py 4.2.0.",
            },
            " (unknown_catalog_version)",
            id="catalog-version-during-a-release",
        ),
        pytest.param(
            {"code": "unknown_policy", "detail": "There is no policy p."},
            " (unknown_policy)",
            id="policy-the-public-api-checked",
        ),
        pytest.param(
            {"code": "missing_reference", "detail": "A row was deleted."},
            " (missing_reference)",
            id="row-deleted-after-the-checks",
        ),
        pytest.param(
            {"detail": "Region state/zz is not in the catalog version."},
            "",
            id="no-code",
        ),
    ],
)
@pytest.mark.parametrize(("submit", "record", "route_status"), SUBMISSIONS)
def test_a_400_naming_none_of_the_callers_rows_is_unavailable(
    submit, record: str, route_status, body: dict[str, str], stated_code: str
) -> None:
    # A 400 the caller cannot act on is a state of the simulation service,
    # such as a catalog version missing while a release deploys.
    service = RecordingService(status_code=400, body=body)

    with pytest.raises(SimulationServiceUnavailableError) as unavailable:
        submit(service.client())

    assert route_status(unavailable.value) == 503
    assert str(unavailable.value) == (
        f"The simulation service refused the {record}{stated_code}: {body['detail']}"
    )
    assert unavailable.value.created_record_id is None


@pytest.mark.parametrize(
    "body",
    [b"not json", {"detail": {"nested": True}}, {"other": "shape"}],
    ids=["not-json", "nested-detail", "no-detail"],
)
def test_a_refusal_of_another_shape_is_unavailable(body: object) -> None:
    service = RecordingService(status_code=422, body=body)

    with pytest.raises(SimulationServiceUnavailableError):
        service.client().submit_report(report_input())


@pytest.mark.parametrize(
    ("body", "status_and_code"),
    [
        pytest.param(
            {"code": "internal_error", "detail": "The run could not be started."},
            "500 internal_error",
            id="internal-error",
        ),
        pytest.param({"detail": "The run could not be started."}, "500", id="no-code"),
        pytest.param(b"", "500", id="unreadable"),
    ],
)
@pytest.mark.parametrize(("submit", "record", "route_status"), SUBMISSIONS)
def test_an_internal_error_is_not_unavailable(
    submit, record: str, route_status, body: object, status_and_code: str
) -> None:
    # A 500 may come after the service created the record, so it is not a
    # 503, which says the service created nothing.
    service = RecordingService(status_code=500, body=body)

    with pytest.raises(SimulationServiceInternalError) as failed:
        submit(service.client())

    assert route_status(failed.value) == 502
    assert str(failed.value) == possibly_created_message(status_and_code, record)


@pytest.mark.parametrize("status_code", [502, 504])
@pytest.mark.parametrize(("submit", "record", "route_status"), SUBMISSIONS)
def test_a_proxys_answer_in_place_of_the_services_is_not_unavailable(
    submit, record: str, route_status, status_code: int
) -> None:
    # A proxy in front of the service, such as Cloud Run's front end, may
    # answer 502 or 504 after the service created the record.
    service = RecordingService(status_code=status_code, body=b"upstream timeout")

    with pytest.raises(SimulationServiceAnswerUnreadableError) as lost:
        submit(service.client())

    assert route_status(lost.value) == 502
    assert str(lost.value) == answer_lost_message(
        f"a proxy answered {status_code} in its place", record
    )


@pytest.mark.parametrize("status_code", [401, 403, 404, 405, 413, 429])
@pytest.mark.parametrize(("submit", "record", "route_status"), SUBMISSIONS)
def test_a_status_sent_before_the_services_route_runs_is_unavailable(
    submit, record: str, route_status, status_code: int
) -> None:
    # The gateway, Cloud Run or the service's framework answers these before
    # the service's route runs, so nothing was created.
    service = RecordingService(status_code=status_code, body={"detail": "Not Found"})

    with pytest.raises(SimulationServiceUnavailableError) as unavailable:
        submit(service.client())

    assert route_status(unavailable.value) == 503
    assert str(unavailable.value) == (
        f"The simulation service is unavailable ({status_code})."
    )
    assert unavailable.value.created_record_id is None


@pytest.mark.parametrize(
    ("status_and_body", "status_and_code"),
    [
        pytest.param((200, REPORT_CREATED), "200", id="200-naming-a-record"),
        pytest.param((204, b""), "204", id="204"),
        pytest.param((302, b""), "302", id="302"),
        pytest.param((408, {"detail": "busy"}), "408", id="408"),
        pytest.param(
            (409, {"code": "label_taken", "detail": "The label is taken."}),
            "409 label_taken",
            id="409-with-a-code",
        ),
        pytest.param((501, b"Not Implemented"), "501", id="501"),
    ],
)
@pytest.mark.parametrize(("submit", "record", "route_status"), SUBMISSIONS)
def test_an_unexpected_status_may_have_created_the_record(
    submit,
    record: str,
    route_status,
    status_and_body: tuple[int, object],
    status_and_code: str,
) -> None:
    # The service's route may have written rows before answering a status
    # the Public API does not expect, so the answer is not a 503, which says
    # it created nothing.
    status_code, body = status_and_body
    service = RecordingService(status_code=status_code, body=body)

    with pytest.raises(SimulationServiceAnswerUnreadableError) as unexpected:
        submit(service.client())

    assert route_status(unexpected.value) == 502
    assert str(unexpected.value) == possibly_created_message(status_and_code, record)


@pytest.mark.parametrize(
    ("body", "status_and_code"),
    [
        pytest.param(
            {
                "code": "manifest_unavailable",
                "detail": "The v2 version manifest could not be read.",
            },
            "503 manifest_unavailable",
            id="with-a-code",
        ),
        pytest.param(
            {"detail": "The v2 version manifest could not be read."},
            "503",
            id="no-code",
        ),
    ],
)
@pytest.mark.parametrize(("submit", "record", "route_status"), SUBMISSIONS)
def test_the_services_unavailability_is_passed_on_with_its_code(
    submit, record: str, route_status, body: object, status_and_code: str
) -> None:
    service = RecordingService(status_code=503, body=body)

    with pytest.raises(SimulationServiceUnavailableError) as unavailable:
        submit(service.client())

    assert route_status(unavailable.value) == 503
    assert str(unavailable.value) == (
        f"The simulation service is unavailable ({status_and_code})."
    )
    assert unavailable.value.created_record_id is None


@pytest.mark.parametrize(("submit", "record", "route_status"), SUBMISSIONS)
def test_a_record_the_unavailable_service_created_is_named(
    submit, record: str, route_status
) -> None:
    # The service created the record, then Modal refused the call and the
    # service failed its run: the caller gets the record's ID.
    id_field, record_id = CREATED_RECORD_IDS[record]
    service = RecordingService(
        status_code=503,
        body={
            "code": "modal_call_refused",
            "detail": "Modal refused the call, and the run was failed.",
            id_field: str(record_id),
        },
    )

    with pytest.raises(SimulationServiceUnavailableError) as unavailable:
        submit(service.client())

    assert route_status(unavailable.value) == 503
    assert str(unavailable.value) == (
        f"The simulation service created {record} {record_id}, but is "
        "unavailable (503 modal_call_refused)."
    )
    assert unavailable.value.created_record_id == record_id


@pytest.mark.parametrize(("submit", "record", "route_status"), SUBMISSIONS)
def test_a_503_naming_only_another_records_id_may_have_created_the_record(
    submit, record: str, route_status
) -> None:
    # A report's 503 naming only a simulation shows the service wrote rows,
    # so the answer is not a 503, which says it created nothing.
    other_id_field, other_record_id = OTHER_RECORD_IDS[record]
    service = RecordingService(
        status_code=503,
        body={
            "code": "modal_call_refused",
            "detail": "Modal refused the call.",
            other_id_field: str(other_record_id),
        },
    )

    with pytest.raises(SimulationServiceAnswerUnreadableError) as lost:
        submit(service.client())

    assert route_status(lost.value) == 502
    assert str(lost.value) == possibly_created_message("503 modal_call_refused", record)


@pytest.mark.parametrize(
    ("body", "status_and_code"),
    [
        pytest.param(
            b"upstream connect error or disconnect/reset before headers",
            "503",
            id="proxy-text",
        ),
        pytest.param({"other": "shape"}, "503", id="no-detail"),
        pytest.param(
            {"code": "modal_call_refused"},
            "503 modal_call_refused",
            id="no-detail-with-a-code",
        ),
    ],
)
@pytest.mark.parametrize(("submit", "record", "route_status"), SUBMISSIONS)
def test_a_503_that_cannot_be_read_may_have_created_the_record(
    submit, record: str, route_status, body: object, status_and_code: str
) -> None:
    # Cloud Run's front end answers 503 in the service's place when the
    # service's answer is malformed or the connection to its instance fails,
    # which can follow a request the service received.
    service = RecordingService(status_code=503, body=body)

    with pytest.raises(SimulationServiceAnswerUnreadableError) as lost:
        submit(service.client())

    assert route_status(lost.value) == 502
    assert str(lost.value) == possibly_created_message(status_and_code, record)


@pytest.mark.parametrize(("submit", "record", "route_status"), SUBMISSIONS)
def test_a_503_naming_a_malformed_record_id_may_have_created_the_record(
    submit, record: str, route_status
) -> None:
    # The body names a record, but not one the Public API can use.
    id_field, _record_id = CREATED_RECORD_IDS[record]
    service = RecordingService(
        status_code=503,
        body={
            "code": "modal_call_refused",
            "detail": "Modal refused the call.",
            id_field: "not-a-uuid",
        },
    )

    with pytest.raises(SimulationServiceAnswerUnreadableError) as lost:
        submit(service.client())

    assert route_status(lost.value) == 502
    assert str(lost.value) == possibly_created_message("503 modal_call_refused", record)


@pytest.mark.parametrize(
    ("body", "submit", "record", "route_status"),
    [
        pytest.param(b"not json", submit_report, "report", _report_route_status),
        pytest.param(
            {"report_id": "not-a-uuid", "report_run_id": str(REPORT_RUN_ID)},
            submit_report,
            "report",
            _report_route_status,
        ),
        pytest.param(
            {"status": "pending"}, submit_report, "report", _report_route_status
        ),
        pytest.param(
            b"not json", submit_simulation, "simulation", _simulation_route_status
        ),
        pytest.param(
            {"simulation_id": str(SIMULATION_ID)},
            submit_simulation,
            "simulation",
            _simulation_route_status,
        ),
    ],
    ids=[
        "report-not-json",
        "report-malformed-id",
        "report-no-id",
        "simulation-not-json",
        "simulation-no-run-id",
    ],
)
def test_a_created_answer_that_cannot_be_read_is_not_unavailable(
    body: object, submit, record: str, route_status
) -> None:
    # The service has created the record and started its run, so the caller
    # is told the answer was unreadable rather than to try again.
    service = RecordingService(status_code=201, body=body)

    with pytest.raises(SimulationServiceAnswerUnreadableError) as unreadable:
        submit(service.client())

    assert route_status(unreadable.value) == 502
    assert str(unreadable.value) == (
        f"The simulation service created the {record}, but its answer could not "
        "be read."
    )


def _client_raising(
    error_type: type[httpx.TransportError],
) -> SimulationServiceReportClient:
    """Return a client whose every request fails with ``error_type``."""

    def fail(request: httpx.Request) -> httpx.Response:
        msg = "the transport failed"
        raise error_type(msg, request=request)

    return SimulationServiceReportClient.from_environment(
        transport=httpx.MockTransport(fail)
    )


@pytest.mark.parametrize(
    "error_type", [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout]
)
@pytest.mark.parametrize(("submit", "record", "route_status"), SUBMISSIONS)
def test_a_connection_never_made_is_unavailable(
    submit, record: str, route_status, error_type: type[httpx.TransportError]
) -> None:
    with pytest.raises(
        SimulationServiceUnavailableError, match="could not be reached"
    ) as unavailable:
        submit(_client_raising(error_type))

    assert route_status(unavailable.value) == 503


@pytest.mark.parametrize(
    "error_type",
    [
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.ReadError,
        httpx.WriteError,
        httpx.RemoteProtocolError,
    ],
)
@pytest.mark.parametrize(("submit", "record", "route_status"), SUBMISSIONS)
def test_an_answer_lost_after_sending_is_not_unavailable(
    submit, record: str, route_status, error_type: type[httpx.TransportError]
) -> None:
    # The service may have received the submission and created the record,
    # so the answer is not a 503, which says it created nothing.
    with pytest.raises(SimulationServiceAnswerUnreadableError) as lost:
        submit(_client_raising(error_type))

    assert route_status(lost.value) == 502
    assert str(lost.value) == answer_lost_message(error_type.__name__, record)


def test_a_gateway_token_that_cannot_be_fetched_is_unavailable() -> None:
    def refuse_token(
        http_client: httpx.Client, body: dict[str, Any]
    ) -> SimulationAnswer:
        msg = "Auth0 refused the client credentials"
        raise GatewayAuthError(msg)

    client = SimulationServiceReportClient(
        httpx.Client(base_url=SIMULATION_URL), send_report=refuse_token
    )

    with pytest.raises(
        SimulationServiceUnavailableError, match="could not be reached"
    ) as unavailable:
        client.submit_report(report_input())

    assert _report_route_status(unavailable.value) == 503


def test_each_request_is_sent_through_its_one_replaceable_send_function() -> None:
    sent: list[tuple[str, dict[str, Any]]] = []

    def send_to(path: str, answer: dict[str, str]):
        def send(http_client: httpx.Client, body: dict[str, Any]) -> SimulationAnswer:
            assert str(http_client.base_url).rstrip("/") == SIMULATION_URL
            sent.append((path, body))
            return SimulationAnswer(
                status_code=201, content=json.dumps(answer).encode()
            )

        return send

    client = SimulationServiceReportClient(
        httpx.Client(base_url=SIMULATION_URL),
        send_report=send_to(REPORTS_PATH, REPORT_CREATED),
        send_simulation=send_to(SIMULATIONS_PATH, SIMULATION_CREATED),
    )

    client.submit_report(report_input())
    client.submit_simulation(simulation_input())

    assert [path for path, _body in sent] == [REPORTS_PATH, SIMULATIONS_PATH]


def test_a_missing_service_url_is_unavailable(monkeypatch) -> None:
    monkeypatch.delenv("SIMULATION_ENTRYPOINT_URL")

    with pytest.raises(SimulationServiceUnavailableError, match="not configured"):
        SimulationServiceReportClient.from_environment()


def test_partly_configured_gateway_credentials_are_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("GATEWAY_AUTH_ISSUER", "https://tenant.example.test/")

    with pytest.raises(SimulationServiceUnavailableError, match="not configured"):
        SimulationServiceReportClient.from_environment()
