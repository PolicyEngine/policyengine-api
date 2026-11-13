"""Read v2 budget-window reports over stand-in services."""

from __future__ import annotations

from dataclasses import replace

from policyengine_api.services.v2.stored_reports.budget_window_results.types import (
    BudgetWindowResultUnreadableError,
)
from tests.unit.v2.budget_window_report_support import (
    BUDGET_WINDOW_REPORT_ID,
    BUDGET_WINDOW_RESULT,
    BUDGET_WINDOW_RUN_ID,
    YEAR_RUN_IDS,
    budget_window_report_read,
    budget_window_run_read,
    budget_window_summary_read,
)
from tests.unit.v2.stored_report_support import (
    REPORT_ID,
    FakeReportService,
    report_route_client,
    report_summary_read,
)


def read_item(service: FakeReportService) -> dict:
    response = report_route_client(reports=service).get(
        f"/v2/reports/{BUDGET_WINDOW_REPORT_ID}?country_id=us"
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]["item"]


def test_a_budget_window_answers_its_window_newest_run_years_and_result() -> None:
    service = FakeReportService(report=budget_window_report_read())

    item = read_item(service)

    assert item["kind"] == "budget_window"
    assert (item["year"], item["budget_window_size"]) == (2026, 2)
    run = item["run"]
    assert run["id"] == str(BUDGET_WINDOW_RUN_ID)
    assert (run["status"], run["trigger"], run["recalculate"]) == (
        "succeeded",
        "initial",
        False,
    )
    assert (run["country_package_version"], run["policyengine_version"]) == (
        "1.4.0",
        "4.1.0",
    )
    assert [(year["year"], year["id"]) for year in run["years"]] == [
        (year, str(run_id)) for year, run_id in YEAR_RUN_IDS.items()
    ]
    assert set(run["years"][0]) == {
        "year",
        "id",
        "status",
        "trigger",
        "country_package_version",
        "policyengine_version",
        "baseline_simulation_run_id",
        "reform_simulation_run_id",
        "error_message",
        "created_at",
        "started_at",
        "completed_at",
    }
    assert item["current_versions"] == {
        "country_package_version": "1.5.0",
        "policyengine_version": "4.2.0",
    }
    assert item["result"] == BUDGET_WINDOW_RESULT
    assert service.calls == [
        (
            "get_report",
            {"country_id": "us", "report_id": BUDGET_WINDOW_REPORT_ID, "run_id": None},
        )
    ]


def test_a_budget_window_without_a_run_answers_no_run_and_no_result() -> None:
    service = FakeReportService(
        report=budget_window_report_read(status="not_run", run=None, result=None)
    )

    item = read_item(service)

    assert (item["status"], item["run"], item["result"]) == ("not_run", None, None)


def test_a_window_run_whose_years_are_still_running_answers_no_result() -> None:
    run = budget_window_run_read(status="running", completed_at=None)
    service = FakeReportService(
        report=budget_window_report_read(status="running", run=run, result=None)
    )

    item = read_item(service)

    assert item["run"]["status"] == "running"
    assert item["result"] is None


def test_an_unreadable_window_result_answers_500() -> None:
    service = FakeReportService(
        error=BudgetWindowResultUnreadableError("the window has no 2027 report run")
    )

    response = report_route_client(reports=service).get(
        f"/v2/reports/{BUDGET_WINDOW_REPORT_ID}?country_id=us"
    )

    assert response.status_code == 500
    assert response.json() == {
        "status": "error",
        "message": "The report's stored result cannot be read",
    }


def test_listing_answers_budget_windows_and_economy_reports_without_results() -> None:
    window = budget_window_summary_read()
    service = FakeReportService(listed=(window, report_summary_read()))

    response = report_route_client(reports=service).get(
        f"/v2/reports?country_id=us&report_id={BUDGET_WINDOW_REPORT_ID}"
        f"&report_id={REPORT_ID}"
    )

    assert response.status_code == 200, response.text
    items = response.json()["result"]["items"]
    assert [(item["id"], item["kind"]) for item in items] == [
        (str(BUDGET_WINDOW_REPORT_ID), "budget_window"),
        (str(REPORT_ID), "economy"),
    ]
    assert all("result" not in item for item in items)
    assert [year["year"] for year in items[0]["run"]["years"]] == [2026, 2027]


def test_a_listed_budget_window_without_a_run_answers_no_run() -> None:
    window = replace(budget_window_summary_read(), status="not_run", run=None)
    service = FakeReportService(listed=(window,))

    items = (
        report_route_client(reports=service)
        .get(f"/v2/reports?country_id=us&report_id={BUDGET_WINDOW_REPORT_ID}")
        .json()["result"]["items"]
    )

    assert (items[0]["status"], items[0]["run"]) == ("not_run", None)


def test_the_openapi_document_tells_the_report_kinds_apart_by_kind() -> None:
    document = report_route_client().get("/v2/openapi.json").json()

    schemas = document["components"]["schemas"]
    item = schemas["ReportDetailResult"]["properties"]["item"]
    assert item["discriminator"]["propertyName"] == "kind"
    every_kind = {"economy", "household", "budget_window"}
    assert set(item["discriminator"]["mapping"]) == every_kind
    listed = schemas["ReportListResult"]["properties"]["items"]["items"]
    assert set(listed["discriminator"]["mapping"]) == every_kind
    assert "result" in schemas["BudgetWindowReportItem"]["properties"]
    assert "years" in schemas["BudgetWindowRunItem"]["properties"]
