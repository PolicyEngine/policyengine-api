"""Create budget-window reports through the simulation service; read its answers.

A budget window goes to the same ``POST /reports`` as an economy report, as
``report_type`` ``budget_window``, and the service answers the same way;
its created answer names the report and its budget-window run.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import httpx
import pytest

from policyengine_api.libs.simulation_reports import (
    REPORTS_PATH,
    SimulationServiceReportClient,
)
from policyengine_api.services.v2.simulation_service.types import (
    BudgetWindowReportCreationInput,
    SimulationServiceAnswerUnreadableError,
    SimulationServiceInternalError,
    SimulationServiceInvalidRequestError,
    SimulationServiceUnavailableError,
    SubmittedBudgetWindow,
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
REPORT_ID = UUID("00000000-0000-0000-0000-00000000b101")
BUDGET_WINDOW_RUN_ID = UUID("00000000-0000-0000-0000-00000000b102")
POLICY_ID = UUID("00000000-0000-0000-0000-00000000b103")
DYNAMIC_ID = UUID("00000000-0000-0000-0000-00000000b104")
WINDOW_CREATED = {
    "report_id": str(REPORT_ID),
    "budget_window_run_id": str(BUDGET_WINDOW_RUN_ID),
    "status": "pending",
}


@pytest.fixture(autouse=True)
def configured_simulation_service(monkeypatch):
    """Name the Cloud Run simulation service; set no gateway credentials."""
    for name in ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SIMULATION_ENTRYPOINT_URL", f"{SIMULATION_URL}/")


def window_input(**changes: Any) -> BudgetWindowReportCreationInput:
    values: dict[str, Any] = {
        "country_id": "us",
        "kind": "budget_window",
        "label": "Expanded child tax credit, ten years",
        "year": 2026,
        "budget_window_size": 10,
        "region_code": "us",
        "baseline": {},
        "reform": {"policy_id": str(POLICY_ID)},
    }
    return BudgetWindowReportCreationInput.model_validate({**values, **changes})


class AnsweringService:
    """The simulation service, answering every request with one scripted answer."""

    def __init__(self, status_code: int = 201, body: object = WINDOW_CREATED) -> None:
        self.status_code = status_code
        self.body = body
        self.requests: list[httpx.Request] = []

    def answer(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status_code, json=self.body)

    def submit(self, **changes: Any) -> SubmittedBudgetWindow:
        client = SimulationServiceReportClient.from_environment(
            transport=httpx.MockTransport(self.answer)
        )
        return client.submit_budget_window(window_input(**changes))

    def sent_body(self) -> dict[str, object]:
        (request,) = self.requests
        return json.loads(request.content)


@pytest.mark.parametrize("status_code", [201, 202])
def test_a_budget_window_is_posted_to_reports_and_its_window_run_returned(
    status_code: int,
) -> None:
    service = AnsweringService(status_code=status_code)

    submitted = service.submit()

    assert submitted == SubmittedBudgetWindow(
        report_id=REPORT_ID, budget_window_run_id=BUDGET_WINDOW_RUN_ID
    )
    (request,) = service.requests
    assert request.method == "POST"
    assert str(request.url) == f"{SIMULATION_URL}{REPORTS_PATH}"
    assert service.sent_body() == {
        "country": "us",
        "report_type": "budget_window",
        "label": "Expanded child tax credit, ten years",
        "description": None,
        "year": 2026,
        "budget_window_size": 10,
        "region_code": "us",
        "baseline": {"policy_id": None, "dynamic_id": None},
        "reform": {"policy_id": str(POLICY_ID), "dynamic_id": None},
    }


def test_a_budget_window_sends_its_spm_settings_only_when_given() -> None:
    service = AnsweringService()

    service.submit(
        description="Doubles the credit",
        reform={"policy_id": str(POLICY_ID), "dynamic_id": str(DYNAMIC_ID)},
        spm={"geography_kind": "national"},
    )

    body = service.sent_body()
    assert body["description"] == "Doubles the credit"
    assert body["reform"] == {
        "policy_id": str(POLICY_ID),
        "dynamic_id": str(DYNAMIC_ID),
    }
    assert body["spm"] == {"geography_kind": "national"}
    assert "include_cliffs" not in body


@pytest.mark.parametrize(
    "body",
    [
        {"report_id": str(REPORT_ID)},
        {"report_id": str(REPORT_ID), "report_run_id": str(BUDGET_WINDOW_RUN_ID)},
        {"budget_window_run_id": "not-a-uuid", "report_id": str(REPORT_ID)},
    ],
    ids=["no-window-run", "report-run-instead", "malformed-window-run"],
)
def test_a_created_answer_without_its_window_run_cannot_be_read(body: object) -> None:
    service = AnsweringService(body=body)

    with pytest.raises(
        SimulationServiceAnswerUnreadableError,
        match="created the budget window, but its answer could not be read",
    ):
        service.submit()


def test_a_region_the_caller_named_that_the_service_lacks_is_refused() -> None:
    service = AnsweringService(
        status_code=400,
        body={"code": "unknown_region", "detail": "No region state/zz"},
    )

    with pytest.raises(
        SimulationServiceInvalidRequestError,
        match=r"cannot run this request \(unknown_region\): No region state/zz",
    ):
        service.submit()


def test_a_400_for_the_services_own_state_is_unavailable() -> None:
    service = AnsweringService(
        status_code=400,
        body={"code": "unknown_catalog_version", "detail": "No catalog yet"},
    )

    with pytest.raises(
        SimulationServiceUnavailableError,
        match=r"refused the report \(unknown_catalog_version\): No catalog yet",
    ):
        service.submit()


def test_a_503_naming_the_created_report_gives_its_id() -> None:
    service = AnsweringService(
        status_code=503,
        body={
            "code": "modal_call_refused",
            "detail": "Modal refused a year",
            "report_id": str(REPORT_ID),
        },
    )

    with pytest.raises(SimulationServiceUnavailableError) as raised:
        service.submit()

    assert raised.value.created_record_id == REPORT_ID
    assert "Modal refused" not in str(raised.value)


def test_an_internal_error_may_have_created_the_window() -> None:
    service = AnsweringService(
        status_code=500, body={"code": "internal_error", "detail": "Traceback"}
    )

    with pytest.raises(SimulationServiceInternalError, match="500 internal_error"):
        service.submit()
