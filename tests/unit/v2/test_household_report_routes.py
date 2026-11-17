"""Create, read and list household reports at /v2/reports over stand-in services."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest

from policyengine_api.services.v2.household_calculations.types import (
    HouseholdCalculationOutput,
)
from policyengine_api.services.v2.household_calculations.validators import (
    HouseholdCalculationCountryError,
    HouseholdCalculationYearError,
)
from policyengine_api.services.v2.households.validators import (
    HouseholdNotFoundError,
)
from policyengine_api.services.v2.simulation_service.types import (
    HouseholdReportCreationInput,
)
from policyengine_api.services.v2.stored_reports.household_results.types import (
    HouseholdReportFailure,
    HouseholdReportResult,
    HouseholdReportSideFailure,
    HouseholdResultUnreadableError,
)
from policyengine_api.services.v2.stored_reports.types import (
    HouseholdReportRead,
    HouseholdReportSummaryRead,
    ReportSimulationRead,
)
from tests.unit.v2.stored_report_support import (
    BASELINE_SIMULATION_ID,
    CREATED_AT,
    CURRENT_VERSIONS,
    POLICY_ID,
    REFORM_SIMULATION_ID,
    REPORT_ID,
    FakeReportService,
    report_route_client,
    report_run_read,
    report_summary_read,
)

HOUSEHOLD_ID = UUID("00000000-0000-0000-0000-00000000e001")
REPORTS = "/v2/reports?country_id=us"
BASELINE_HOUSEHOLD = {"people": {"you": {"net_income": {"2026": 30_000.0}}}}
REFORM_HOUSEHOLD = {"people": {"you": {"net_income": {"2026": 31_250.5}}}}


def household_summary_fields(**changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "id": REPORT_ID,
        "country_id": "us",
        "kind": "household",
        "label": "My household under the reform",
        "description": None,
        "year": 2026,
        "household_id": HOUSEHOLD_ID,
        "baseline_simulation": ReportSimulationRead(
            id=BASELINE_SIMULATION_ID, policy_id=None, dynamic_id=None
        ),
        "reform_simulation": ReportSimulationRead(
            id=REFORM_SIMULATION_ID, policy_id=POLICY_ID, dynamic_id=None
        ),
        "options": {},
        "created_at": CREATED_AT,
        "status": "succeeded",
        "run": report_run_read(),
        "current_versions": CURRENT_VERSIONS,
    }
    return {**values, **changes}


def household_report_read(**changes: Any) -> HouseholdReportRead:
    fields = {
        "result": HouseholdReportResult(
            baseline=HouseholdCalculationOutput(
                household=BASELINE_HOUSEHOLD,
                warnings=(),
                spm_config=None,
                spm_provenance=None,
            ),
            reform=HouseholdCalculationOutput(
                household=REFORM_HOUSEHOLD,
                warnings=("ignored_input",),
                spm_config={"geography_kind": "national"},
                spm_provenance={"scenario": "baseline"},
            ),
        ),
        "failure": None,
        **household_summary_fields(),
        **changes,
    }
    return HouseholdReportRead(**fields)


def household_body(**changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "country_id": "us",
        "kind": "household",
        "label": "My household under the reform",
        "household_id": str(HOUSEHOLD_ID),
        "baseline": {},
        "reform": {"policy_id": str(POLICY_ID)},
    }
    return {**values, **changes}


def test_a_household_report_is_created_and_answered_as_stored() -> None:
    service = FakeReportService(
        report=household_report_read(
            status="pending",
            run=report_run_read(status="pending", completed_at=None),
            result=None,
        )
    )

    response = report_route_client(reports=service).post(REPORTS, json=household_body())

    assert response.status_code == 201
    item = response.json()["result"]["item"]
    assert item["kind"] == "household"
    assert item["household_id"] == str(HOUSEHOLD_ID)
    assert item["status"] == "pending"
    assert item["result"] is None
    assert item["options"] == {}
    ((name, arguments),) = service.calls
    assert name == "create_report"
    report_input = arguments["report_input"]
    assert isinstance(report_input, HouseholdReportCreationInput)
    assert report_input.model_dump() == (
        HouseholdReportCreationInput.model_validate(household_body()).model_dump()
    )


def test_a_household_report_of_the_baseline_alone_can_be_created() -> None:
    service = FakeReportService(
        report=household_report_read(reform_simulation=None, result=None)
    )
    body = household_body()
    del body["reform"]

    response = report_route_client(reports=service).post(REPORTS, json=body)

    assert response.status_code == 201
    assert response.json()["result"]["item"]["reform_simulation"] is None
    ((_, arguments),) = service.calls
    assert arguments["report_input"].reform is None


@pytest.mark.parametrize(
    "changes",
    [
        # A label is optional and unused, but one that is sent is checked.
        pytest.param({"label": ""}, id="empty-label"),
        # The report is for the household's default year, so it names none.
        pytest.param({"year": 2026}, id="year"),
        pytest.param({"household_id": None}, id="no-household"),
        pytest.param({"region_code": "us"}, id="economy-field"),
        pytest.param({"include_cliffs": True}, id="economy-option"),
        pytest.param({"kind": "budget"}, id="unknown-kind"),
        # A household report always adds every variable the household lacks.
        pytest.param({"add_missing_variables": True}, id="add-missing-variables"),
    ],
)
def test_a_household_report_outside_its_schema_is_refused_with_422(
    changes: dict[str, Any],
) -> None:
    service = FakeReportService()
    body = {
        name: value
        for name, value in household_body(**changes).items()
        if value is not None
    }

    response = report_route_client(reports=service).post(REPORTS, json=body)

    assert response.status_code == 422
    assert service.calls == []


def test_a_household_report_naming_another_country_is_refused_with_400() -> None:
    service = FakeReportService()

    response = report_route_client(reports=service).post(
        REPORTS, json=household_body(country_id="uk")
    )

    assert response.status_code == 400
    assert service.calls == []


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        pytest.param(
            HouseholdCalculationCountryError(
                "Household calculations are not available for country us."
            ),
            422,
            id="no-household-calculations",
        ),
        pytest.param(
            HouseholdNotFoundError(f"Household {HOUSEHOLD_ID} was not found"),
            404,
            id="household-not-stored",
        ),
        pytest.param(
            HouseholdCalculationYearError(
                "This household has no default year to calculate."
            ),
            422,
            id="household-without-default-year",
        ),
    ],
)
def test_a_household_report_the_checks_refuse_is_answered_with_its_reason(
    error: Exception, status_code: int
) -> None:
    service = FakeReportService(error=error)

    response = report_route_client(reports=service).post(REPORTS, json=household_body())

    assert response.status_code == status_code
    assert response.json()["message"] == str(error)


def test_a_household_report_answers_both_calculated_households() -> None:
    service = FakeReportService(report=household_report_read())

    response = report_route_client(reports=service).get(
        f"/v2/reports/{REPORT_ID}?country_id=us"
    )

    assert response.status_code == 200
    item = response.json()["result"]["item"]
    assert item["kind"] == "household"
    assert item["household_id"] == str(HOUSEHOLD_ID)
    assert item["year"] == 2026
    assert "region_code" not in item
    assert item["run"]["baseline_simulation_run_id"] is not None
    assert item["result"] == {
        "baseline": {
            "household": BASELINE_HOUSEHOLD,
            "warnings": [],
            "spm_config": None,
            "spm_provenance": None,
        },
        "reform": {
            "household": REFORM_HOUSEHOLD,
            "warnings": ["ignored_input"],
            "spm_config": {"geography_kind": "national"},
            "spm_provenance": {"scenario": "baseline"},
        },
    }


def test_a_household_report_of_the_baseline_alone_answers_no_reform() -> None:
    report = household_report_read(reform_simulation=None)
    assert report.result is not None
    service = FakeReportService(
        report=replace(report, result=replace(report.result, reform=None))
    )

    item = (
        report_route_client(reports=service)
        .get(f"/v2/reports/{REPORT_ID}?country_id=us")
        .json()["result"]["item"]
    )

    assert item["reform_simulation"] is None
    assert item["result"]["reform"] is None


def test_a_failed_household_report_answers_each_sides_failure() -> None:
    service = FakeReportService(
        report=household_report_read(
            status="failed",
            run=report_run_read(
                status="failed", error_message="household_calculation_failed"
            ),
            result=None,
            failure=HouseholdReportFailure(
                baseline=None,
                reform=HouseholdReportSideFailure(
                    code="invalid_inputs",
                    message="The household names inputs the model does not have.",
                    input_errors=({"name": "employment_incme"},),
                    spm_error=None,
                ),
            ),
        )
    )

    item = (
        report_route_client(reports=service)
        .get(f"/v2/reports/{REPORT_ID}?country_id=us")
        .json()["result"]["item"]
    )

    assert item["result"] is None
    assert item["failure"] == {
        "baseline": None,
        "reform": {
            "code": "invalid_inputs",
            "message": "The household names inputs the model does not have.",
            "input_errors": [{"name": "employment_incme"}],
            "spm_error": None,
        },
    }


def test_a_household_report_whose_households_cannot_be_read_answers_500() -> None:
    service = FakeReportService(
        error=HouseholdResultUnreadableError("simulation run has no result")
    )

    response = report_route_client(reports=service).get(
        f"/v2/reports/{REPORT_ID}?country_id=us"
    )

    assert response.status_code == 500
    assert response.json()["message"] == "The report's stored result cannot be read"


def test_a_list_answers_household_and_economy_reports_by_kind_without_results() -> None:
    service = FakeReportService(
        listed=(
            HouseholdReportSummaryRead(**household_summary_fields()),
            report_summary_read(),
        )
    )

    response = report_route_client(reports=service).get(
        f"/v2/reports?country_id=us&report_id={REPORT_ID}"
    )

    assert response.status_code == 200
    household_item, economy_item = response.json()["result"]["items"]
    assert household_item["kind"] == "household"
    assert household_item["household_id"] == str(HOUSEHOLD_ID)
    assert "result" not in household_item
    assert "failure" not in household_item
    assert economy_item["kind"] == "economy"
    assert "result" not in economy_item


def test_the_create_routes_schema_offers_the_household_kind() -> None:
    schema = report_route_client(reports=FakeReportService()).get("/v2/openapi.json")

    components = schema.json()["components"]["schemas"]
    household_request = components["HouseholdReportCreateRequest"]
    assert household_request["properties"]["kind"]["const"] == "household"
    assert set(household_request["required"]) >= {
        "country_id",
        "kind",
        "household_id",
        "baseline",
    }
    # A report's name is each user's saved report's.
    assert "label" not in household_request["required"]
    assert "year" not in household_request["properties"]
    # Each side's failure is read from the household function's failure
    # document, which always names its code.
    side_failure = components["HouseholdReportSideFailureItem"]
    assert side_failure["properties"]["code"] == {"title": "Code", "type": "string"}
    assert "submit" not in side_failure["description"]
    assert "HouseholdReportItem" in components
