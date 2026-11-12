"""Create household reports through the simulation service's ``POST /reports``.

A household report goes to the same route as an economy report and is
answered the same way, so these tests check its request body and a sample of
the answers; ``test_simulation_reports`` checks every answer.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from policyengine_api.fastapi_routes.v2.reports.routes import REPORT_ERROR_MAPPINGS
from policyengine_api.libs.simulation_reports import (
    REPORTS_PATH,
    household_report_request,
)
from policyengine_api.services.v2.simulation_service.types import (
    HouseholdReportCreationInput,
    SimulationServiceInternalError,
    SimulationServiceInvalidRequestError,
    SimulationServiceUnavailableError,
    SubmittedReport,
)
from tests.unit.libs.test_simulation_reports import (
    ENVIRONMENT_VARIABLES,
    POLICY_ID,
    REPORT_CREATED,
    REPORT_ID,
    REPORT_RUN_ID,
    SIMULATION_URL,
    RecordingService,
)

HOUSEHOLD_ID = UUID("00000000-0000-0000-0000-00000000b101")


@pytest.fixture(autouse=True)
def configured_simulation_service(monkeypatch):
    """Name the Cloud Run simulation service; set no gateway credentials."""
    for name in ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SIMULATION_ENTRYPOINT_URL", f"{SIMULATION_URL}/")


def household_report_input(**changes: Any) -> HouseholdReportCreationInput:
    values: dict[str, Any] = {
        "country_id": "uk",
        "kind": "household",
        "label": "My household under the reform",
        "household_id": str(HOUSEHOLD_ID),
        "baseline": {},
        "reform": {"policy_id": str(POLICY_ID)},
    }
    return HouseholdReportCreationInput.model_validate({**values, **changes})


def test_a_household_report_is_posted_and_the_created_report_returned() -> None:
    service = RecordingService()

    submitted = service.client().submit_household_report(
        household_report_input(description="Doubles the credit")
    )

    assert submitted == SubmittedReport(
        report_id=REPORT_ID, report_run_id=REPORT_RUN_ID
    )
    (request,) = service.requests
    assert request.method == "POST"
    assert str(request.url) == f"{SIMULATION_URL}{REPORTS_PATH}"
    assert service.sent_body() == {
        "country": "uk",
        "report_type": "household",
        "label": "My household under the reform",
        "description": "Doubles the credit",
        "household_id": str(HOUSEHOLD_ID),
        "baseline": {"policy_id": None},
        "reform": {"policy_id": str(POLICY_ID)},
        "add_missing_variables": False,
    }


def test_a_report_of_the_baseline_alone_sends_a_null_reform() -> None:
    body = household_report_input(
        baseline={"policy_id": str(POLICY_ID)},
        reform=None,
        add_missing_variables=True,
    )

    assert household_report_request(body) == {
        "country": "uk",
        "report_type": "household",
        "label": "My household under the reform",
        "description": None,
        "household_id": str(HOUSEHOLD_ID),
        "baseline": {"policy_id": str(POLICY_ID)},
        "reform": None,
        "add_missing_variables": True,
    }


def test_a_household_report_the_service_refuses_is_reported_with_its_reason() -> None:
    service = RecordingService(
        status_code=422,
        body={
            "code": "household_not_calculable",
            "detail": "The household has no default year",
        },
    )

    with pytest.raises(SimulationServiceInvalidRequestError) as refused:
        service.client().submit_household_report(household_report_input())

    assert str(refused.value) == (
        "The simulation service cannot run this request (household_not_calculable): "
        "The household has no default year"
    )


@pytest.mark.parametrize(
    "code", ["unknown_household", "no_household_function", "unknown_policy"]
)
def test_a_household_400_the_public_api_checked_first_is_unavailable(
    code: str,
) -> None:
    # The Public API checks the household and policies before sending, and
    # the default worker's household function is the service's own state.
    service = RecordingService(
        status_code=400, body={"code": code, "detail": "No such row."}
    )

    with pytest.raises(SimulationServiceUnavailableError) as unavailable:
        service.client().submit_household_report(household_report_input())

    route_status = next(
        mapping.status_code
        for mapping in REPORT_ERROR_MAPPINGS
        if isinstance(unavailable.value, mapping.error_types)
    )
    assert route_status == 503
    assert str(unavailable.value) == (
        f"The simulation service refused the report ({code}): No such row."
    )
    assert unavailable.value.created_record_id is None


def test_a_household_report_the_unavailable_service_created_is_named() -> None:
    service = RecordingService(
        status_code=503,
        body={
            "code": "modal_call_refused",
            "detail": "Modal refused the call, and the run was failed.",
            "report_id": str(REPORT_ID),
        },
    )

    with pytest.raises(SimulationServiceUnavailableError) as unavailable:
        service.client().submit_household_report(household_report_input())

    assert unavailable.value.created_record_id == REPORT_ID
    assert str(unavailable.value) == (
        f"The simulation service created report {REPORT_ID}, but is "
        "unavailable (503 modal_call_refused)."
    )


def test_a_household_report_the_service_failed_may_have_been_created() -> None:
    service = RecordingService(
        status_code=500, body={"code": "internal_error", "detail": "boom"}
    )

    with pytest.raises(SimulationServiceInternalError, match="500 internal_error"):
        service.client().submit_household_report(household_report_input())


def test_an_answer_with_fields_the_public_api_does_not_read_is_accepted() -> None:
    service = RecordingService(
        body={**REPORT_CREATED, "baseline_simulation_id": str(HOUSEHOLD_ID)}
    )

    submitted = service.client().submit_household_report(household_report_input())

    assert submitted.report_id == REPORT_ID
