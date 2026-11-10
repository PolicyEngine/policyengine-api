"""Create simulations and reports through the simulation service; read its answers."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import httpx
import pytest

from policyengine_api.libs.gateway_auth import GatewayAuthError
from policyengine_api.libs.simulation_reports import (
    REPORTS_PATH,
    SIMULATIONS_PATH,
    SimulationAnswer,
    SimulationServiceReportClient,
)
from policyengine_api.services.v2.simulation_service.types import (
    EconomyReportCreationInput,
    EconomySimulationCreationInput,
    SimulationServiceAnswerUnreadableError,
    SimulationServiceInternalError,
    SimulationServiceRefusalError,
    SimulationServiceUnavailableError,
    SubmittedReport,
    SubmittedSimulation,
)
from policyengine_api.spm import SPMSelection

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
        "dataset_name": None,
        "baseline": {"policy_id": None, "dynamic_id": None},
        "reform": {"policy_id": str(POLICY_ID), "dynamic_id": None},
        "include_cliffs": False,
    }


def test_a_report_sends_its_options_and_spm_settings_only_when_given() -> None:
    service = RecordingService()

    service.client().submit_report(
        report_input(
            include_cliffs=True,
            dataset_name="enhanced_cps_2024",
            description="Doubles the credit",
            reform={"policy_id": str(POLICY_ID), "dynamic_id": str(DYNAMIC_ID)},
            spm={"geography_kind": "national"},
        )
    )

    body = service.sent_body()
    assert body["include_cliffs"] is True
    assert body["dataset_name"] == "enhanced_cps_2024"
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
        "dataset_name": None,
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

    with pytest.raises(SimulationServiceRefusalError) as refused:
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

    with pytest.raises(SimulationServiceRefusalError) as refused:
        service.client().submit_report(report_input())

    assert str(refused.value) == (
        "The simulation service cannot run this request: "
        "year: too late; reform.policy_id: bad"
    )


def test_a_row_the_service_cannot_find_is_refused_with_its_reason() -> None:
    service = RecordingService(
        status_code=400,
        body={"detail": "region state/zz is not in the current catalog version"},
    )

    with pytest.raises(SimulationServiceRefusalError, match="state/zz"):
        service.client().submit_report(report_input())


@pytest.mark.parametrize(
    "body",
    [b"not json", {"detail": {"nested": True}}, {"other": "shape"}],
    ids=["not-json", "nested-detail", "no-detail"],
)
def test_a_refusal_of_another_shape_is_unavailable(body: object) -> None:
    service = RecordingService(status_code=422, body=body)

    with pytest.raises(SimulationServiceUnavailableError):
        service.client().submit_report(report_input())


def test_an_internal_error_is_not_unavailable() -> None:
    service = RecordingService(status_code=500, body={"detail": "internal_error"})

    with pytest.raises(SimulationServiceInternalError):
        service.client().submit_report(report_input())


@pytest.mark.parametrize("status_code", [200, 302, 404, 409, 503])
def test_any_other_answer_is_unavailable(status_code: int) -> None:
    service = RecordingService(status_code=status_code, body={"detail": "busy"})

    with pytest.raises(SimulationServiceUnavailableError, match=str(status_code)):
        service.client().submit_report(report_input())


@pytest.mark.parametrize(
    "body",
    [b"not json", {"report_id": "not-a-uuid"}, {"status": "pending"}],
    ids=["not-json", "malformed-id", "no-id"],
)
def test_a_created_answer_that_cannot_be_read_is_not_unavailable(
    body: object,
) -> None:
    service = RecordingService(status_code=201, body=body)

    with pytest.raises(SimulationServiceAnswerUnreadableError):
        service.client().submit_report(report_input())


def test_an_unreachable_service_is_unavailable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        msg = "connection refused"
        raise httpx.ConnectError(msg, request=request)

    client = SimulationServiceReportClient.from_environment(
        transport=httpx.MockTransport(refuse)
    )

    with pytest.raises(SimulationServiceUnavailableError, match="could not be reached"):
        client.submit_simulation(simulation_input())


def test_a_gateway_token_that_cannot_be_fetched_is_unavailable() -> None:
    def refuse_token(
        http_client: httpx.Client, body: dict[str, Any]
    ) -> SimulationAnswer:
        msg = "Auth0 refused the client credentials"
        raise GatewayAuthError(msg)

    client = SimulationServiceReportClient(
        httpx.Client(base_url=SIMULATION_URL), send_report=refuse_token
    )

    with pytest.raises(SimulationServiceUnavailableError, match="could not be reached"):
        client.submit_report(report_input())


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
