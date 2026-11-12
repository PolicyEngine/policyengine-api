"""Read v2 budget-window reports, their years and results from migrated PostgreSQL.

A budget window's calculation is a ``budget_window_runs`` row, and each year
of it a report run naming that row and its year, as the simulation service
creates them. The routes run as the Public API's runtime role, so the tests
prove the role's declared privileges cover every read (rule
``api.v2.runtime-privileges-tested-as-runtime-role``).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from flask import Flask
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlmodel import Session

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.constants import REPO
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.services.v2.simulation_service.types import PackageVersions
from policyengine_api.services.v2.stored_reports.database_session import (
    StoredReportDatabaseSession,
)
from policyengine_api.services.v2.stored_reports.services import V2StoredReportService
from tests.fixtures.economy_results import RunIds, uk_economy_result, us_economy_result
from tests.integration.stored_report_rows import (
    STARTED_AT,
    BudgetWindowYear,
    RunSettings,
    delete_catalog,
    store_budget_window_run,
    store_catalog,
    store_report,
    store_report_run,
    store_year_simulations,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Connection, Engine

    from tests.integration.stored_report_rows import CatalogRows, StoredReport

CURRENT_VERSIONS = {"country_package_version": "1.5.0", "policyengine_version": "4.2.0"}
OLDER_VERSIONS = {"country_package_version": "1.4.0", "policyengine_version": "4.1.0"}
LARGER_RUN_ID = UUID("ffffffff-0000-4000-8000-000000000002")
SMALLER_RUN_ID = UUID("00000000-0000-4000-8000-000000000002")
# Each year's tax revenue, US state income tax and benefit spending changes.
YEAR_BUDGETS = {
    2026: (1500.0, 250.0, -500.0),
    2027: (1700.0, 300.0, -400.0),
    2028: (1900.0, 350.0, -300.0),
}


def current_versions(country_id: str) -> PackageVersions:
    return PackageVersions(**CURRENT_VERSIONS)


@pytest.fixture
def owner_engine(disposable_v2_database_url: str) -> Iterator[Engine]:
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    engine = create_engine(disposable_v2_database_url, poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture
def catalogs(owner_engine: Engine) -> Iterator[dict[str, CatalogRows]]:
    """Store a US and a UK catalog, and delete them and their reports after."""
    with owner_engine.begin() as connection:
        stored = {
            country: store_catalog(connection, country) for country in ("us", "uk")
        }
    yield stored
    with owner_engine.begin() as connection:
        for catalog in stored.values():
            delete_catalog(connection, catalog)


@pytest.fixture
def client(managed_v2_roles, v2_engine_as_role) -> Iterator[TestClient]:
    """Serve the report routes as the runtime role."""
    runtime_engine = v2_engine_as_role(managed_v2_roles.runtime, poolclass=NullPool)
    sessions = sessionmaker(runtime_engine, class_=Session)
    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        v2_stored_report_service_factory=lambda: V2StoredReportService(
            StoredReportDatabaseSession(sessions), current_versions=current_versions
        ),
    )
    settings = RouteImplementationSettings(
        health=RouteImplementation.FLASK_FALLBACK,
        specification=RouteImplementation.FLASK_FALLBACK,
        metadata=RouteImplementation.FLASK_FALLBACK,
    )
    yield TestClient(
        create_asgi_app(
            Flask(__name__), dependencies=dependencies, route_settings=settings
        )
    )
    runtime_engine.dispose()


def year_result(country: str, year: int) -> dict[str, Any]:
    """Return an economy result of the country with that year's budget changes."""
    output = copy.deepcopy(
        us_economy_result() if country == "us" else uk_economy_result()
    )
    tax, state_tax, benefits = YEAR_BUDGETS[year]
    output["budget"].update(
        tax_revenue_impact=tax,
        state_tax_revenue_impact=state_tax if country == "us" else 0.0,
        benefit_spending_impact=benefits,
        budgetary_impact=tax - benefits,
    )
    return output


@dataclass(frozen=True)
class StoredWindow:
    """A window run's settings, and each of its years' status.

    A succeeded year stores its result unless ``with_results`` is false.
    """

    settings: RunSettings
    year_statuses: dict[int, str]
    with_results: bool = True


def store_window(
    connection: Connection,
    catalog: CatalogRows,
    report: StoredReport,
    window: StoredWindow,
) -> tuple[UUID, dict[int, RunIds]]:
    """Store a window run and its years, each under that year's simulations.

    Return the window run's ID and each year's report and simulation run IDs.
    """
    settings = window.settings
    window_run_id = store_budget_window_run(connection, catalog, report, settings)
    year_run_ids = {}
    for year, status in window.year_statuses.items():
        run_ids = store_report_run(
            connection,
            catalog,
            store_year_simulations(connection, catalog, report, year),
            RunSettings(
                versions=settings.versions,
                status=status,
                created_at=settings.created_at,
                error_message=(
                    "budget_window_failed: Another year of the budget window "
                    "failed before this year started."
                    if status == "failed"
                    else None
                ),
                budget_window_year=BudgetWindowYear(
                    budget_window_run_id=window_run_id, year=year
                ),
            ),
            result=(
                year_result(catalog.country, year)
                if window.with_results and status == "succeeded"
                else None
            ),
        )
        year_run_ids[year] = run_ids
    return window_run_id, year_run_ids


def read_item(client: TestClient, report_id: UUID, country: str) -> dict[str, Any]:
    response = client.get(f"/v2/reports/{report_id}?country_id={country}")
    assert response.status_code == 200, response.text
    return response.json()["result"]["item"]


def test_a_budget_window_reads_its_newest_run_years_and_result(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    catalog = catalogs["us"]
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog, budget_window_size=3)
        window_run_id, year_run_ids = store_window(
            connection,
            catalog,
            report,
            StoredWindow(
                RunSettings(versions=OLDER_VERSIONS),
                dict.fromkeys(YEAR_BUDGETS, "succeeded"),
            ),
        )

    item = read_item(client, report.report_id, "us")

    assert item["kind"] == "budget_window"
    assert (item["year"], item["budget_window_size"]) == (2026, 3)
    assert item["region_code"] == "state/ca"
    assert item["options"] == {"include_cliffs": True}
    assert item["status"] == "succeeded"
    run = item["run"]
    assert run["id"] == str(window_run_id)
    assert (run["status"], run["trigger"], run["recalculate"]) == (
        "succeeded",
        "initial",
        False,
    )
    assert (run["country_package_version"], run["policyengine_version"]) == (
        "1.4.0",
        "4.1.0",
    )
    assert [(year["year"], year["id"], year["status"]) for year in run["years"]] == [
        (year, str(year_run_ids[year].report_run_id), "succeeded")
        for year in YEAR_BUDGETS
    ]
    # Each year answers the simulation runs its own report run names.
    assert [
        (year["baseline_simulation_run_id"], year["reform_simulation_run_id"])
        for year in run["years"]
    ] == [
        (
            str(year_run_ids[year].baseline_simulation_run_id),
            str(year_run_ids[year].reform_simulation_run_id),
        )
        for year in YEAR_BUDGETS
    ]
    assert item["current_versions"] == CURRENT_VERSIONS
    result = item["result"]
    assert (result["kind"], result["startYear"], result["endYear"]) == (
        "budgetWindow",
        "2026",
        "2028",
    )
    assert [year["budgetaryImpact"] for year in result["annualImpacts"]] == [
        2000.0,
        2100.0,
        2200.0,
    ]
    assert result["annualImpacts"][0]["federalTaxRevenueImpact"] == 1250.0
    assert (
        result["annualImpacts"][0]["spm_provenance"]
        == (us_economy_result()["spm_provenance"])
    )
    assert result["totals"]["taxRevenueImpact"] == 5100.0
    assert result["totals"]["year"] == "Total"


def test_a_uk_budget_window_has_no_state_tax(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    catalog = catalogs["uk"]
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog, budget_window_size=2)
        store_window(
            connection,
            catalog,
            report,
            StoredWindow(
                RunSettings(versions=CURRENT_VERSIONS),
                {2026: "succeeded", 2027: "succeeded"},
            ),
        )

    result = read_item(client, report.report_id, "uk")["result"]

    assert [year["stateTaxRevenueImpact"] for year in result["annualImpacts"]] == [
        0.0,
        0.0,
    ]
    assert result["totals"]["federalTaxRevenueImpact"] == 3200.0


def test_a_running_window_answers_each_years_status_without_a_result(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    catalog = catalogs["us"]
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog, budget_window_size=3)
        store_window(
            connection,
            catalog,
            report,
            StoredWindow(
                RunSettings(versions=CURRENT_VERSIONS, status="running"),
                {2026: "succeeded", 2027: "running", 2028: "pending"},
            ),
        )

    item = read_item(client, report.report_id, "us")

    assert item["status"] == "running"
    assert [year["status"] for year in item["run"]["years"]] == [
        "succeeded",
        "running",
        "pending",
    ]
    assert item["run"]["completed_at"] is None
    assert item["result"] is None


def test_a_failed_window_says_why_and_which_years_failed(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    catalog = catalogs["us"]
    message = "budget_window_year_failed: The budget window's 2027 report run failed."
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog, budget_window_size=3)
        store_window(
            connection,
            catalog,
            report,
            StoredWindow(
                RunSettings(
                    versions=CURRENT_VERSIONS, status="failed", error_message=message
                ),
                {2026: "succeeded", 2027: "failed", 2028: "failed"},
            ),
        )

    item = read_item(client, report.report_id, "us")

    assert item["status"] == "failed"
    assert item["run"]["error_message"] == message
    assert item["run"]["years"][2]["error_message"].startswith("budget_window_failed")
    assert item["result"] is None


def test_a_budget_window_with_no_run_answers_its_definition(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    catalog = catalogs["us"]
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog, budget_window_size=10)

    item = read_item(client, report.report_id, "us")

    assert (item["kind"], item["budget_window_size"]) == ("budget_window", 10)
    assert (item["status"], item["run"], item["result"]) == ("not_run", None, None)


def test_the_newest_window_run_is_read_even_when_an_older_one_succeeded(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    catalog = catalogs["us"]
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog, budget_window_size=2)
        store_window(
            connection,
            catalog,
            report,
            StoredWindow(
                RunSettings(versions=OLDER_VERSIONS),
                {2026: "succeeded", 2027: "succeeded"},
            ),
        )
        newest_run_id, _ = store_window(
            connection,
            catalog,
            report,
            StoredWindow(
                RunSettings(
                    versions=CURRENT_VERSIONS,
                    status="pending",
                    created_at=STARTED_AT + timedelta(days=1),
                ),
                {2026: "pending", 2027: "pending"},
            ),
        )

    item = read_item(client, report.report_id, "us")

    assert item["run"]["id"] == str(newest_run_id)
    assert item["run"]["country_package_version"] == "1.5.0"
    assert item["status"] == "pending"
    assert item["result"] is None


def test_of_two_window_runs_created_together_the_larger_id_is_the_newest(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    catalog = catalogs["us"]
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog, budget_window_size=1)
        # The larger ID is stored first, so insertion order can't pick it.
        for run_id, status in ((LARGER_RUN_ID, "failed"), (SMALLER_RUN_ID, "pending")):
            store_window(
                connection,
                catalog,
                report,
                StoredWindow(
                    RunSettings(
                        versions=CURRENT_VERSIONS, status=status, run_id=run_id
                    ),
                    {2026: status},
                ),
            )

    item = read_item(client, report.report_id, "us")

    assert item["run"]["id"] == str(LARGER_RUN_ID)
    assert item["status"] == "failed"


def test_a_succeeded_window_missing_a_years_result_is_unreadable(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    catalog = catalogs["us"]
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog, budget_window_size=2)
        store_window(
            connection,
            catalog,
            report,
            StoredWindow(
                RunSettings(versions=CURRENT_VERSIONS),
                {2026: "succeeded", 2027: "succeeded"},
                with_results=False,
            ),
        )

    response = client.get(f"/v2/reports/{report.report_id}?country_id=us")

    assert response.status_code == 500
    assert response.json() == {
        "status": "error",
        "message": "The report's stored result cannot be read",
    }


def test_a_budget_window_is_not_found_in_another_country(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    catalog = catalogs["us"]
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog, budget_window_size=2)

    response = client.get(f"/v2/reports/{report.report_id}?country_id=uk")

    assert response.status_code == 404


def test_listing_answers_budget_windows_with_their_years_beside_economy_reports(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    catalog = catalogs["us"]
    with owner_engine.begin() as connection:
        economy = store_report(connection, catalog)
        store_report_run(
            connection,
            catalog,
            economy,
            RunSettings(versions=CURRENT_VERSIONS),
            result=us_economy_result(),
        )
        succeeded_window = store_report(connection, catalog, budget_window_size=2)
        window_run_id, _ = store_window(
            connection,
            catalog,
            succeeded_window,
            StoredWindow(
                RunSettings(versions=CURRENT_VERSIONS),
                {2026: "succeeded", 2027: "succeeded"},
            ),
        )
        unrun_window = store_report(connection, catalog, budget_window_size=5)
    named = (
        succeeded_window.report_id,
        uuid4(),
        economy.report_id,
        unrun_window.report_id,
        succeeded_window.report_id,
    )

    response = client.get(
        "/v2/reports?country_id=us&"
        + "&".join(f"report_id={report_id}" for report_id in named)
    )

    assert response.status_code == 200, response.text
    items = response.json()["result"]["items"]
    assert [(item["id"], item["kind"]) for item in items] == [
        (str(succeeded_window.report_id), "budget_window"),
        (str(economy.report_id), "economy"),
        (str(unrun_window.report_id), "budget_window"),
    ]
    assert all("result" not in item for item in items)
    window = items[0]
    assert window["run"]["id"] == str(window_run_id)
    assert [year["year"] for year in window["run"]["years"]] == [2026, 2027]
    assert (items[2]["status"], items[2]["run"]) == ("not_run", None)


def test_a_succeeded_window_whose_result_cannot_be_read_is_still_listed(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    # Listing never reads the window's figures, so a window whose years
    # stored no result rows is listed like any other.
    catalog = catalogs["us"]
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog, budget_window_size=2)
        store_window(
            connection,
            catalog,
            report,
            StoredWindow(
                RunSettings(versions=CURRENT_VERSIONS),
                {2026: "succeeded", 2027: "succeeded"},
                with_results=False,
            ),
        )

    response = client.get(f"/v2/reports?country_id=us&report_id={report.report_id}")

    assert response.status_code == 200, response.text
    (item,) = response.json()["result"]["items"]
    assert (item["kind"], item["status"]) == ("budget_window", "succeeded")
    assert "result" not in item


def test_listing_reads_any_number_of_windows_in_two_queries(
    owner_engine: Engine,
    catalogs: dict[str, CatalogRows],
    managed_v2_roles,
    v2_engine_as_role,
) -> None:
    catalog = catalogs["us"]
    with owner_engine.begin() as connection:
        reports = [store_report(connection, catalog)]
        for _ in range(3):
            window = store_report(connection, catalog, budget_window_size=2)
            store_window(
                connection,
                catalog,
                window,
                StoredWindow(
                    RunSettings(versions=CURRENT_VERSIONS),
                    {2026: "succeeded", 2027: "running"},
                ),
            )
            reports.append(window)
    runtime_engine = v2_engine_as_role(managed_v2_roles.runtime, poolclass=NullPool)
    statements: list[str] = []

    def record_statement(
        _connection: Any, _cursor: Any, statement: str, *_arguments: Any
    ) -> None:
        statements.append(statement)

    event.listen(runtime_engine, "before_cursor_execute", record_statement)
    service = V2StoredReportService(
        StoredReportDatabaseSession(sessionmaker(runtime_engine, class_=Session)),
        current_versions=current_versions,
    )

    listed = service.list_reports(
        country_id="us", report_ids=[report.report_id for report in reports]
    )
    runtime_engine.dispose()

    assert [read.kind for read in listed] == [
        "economy",
        "budget_window",
        "budget_window",
        "budget_window",
    ]
    assert [statement.split()[0] for statement in statements] == ["SELECT", "SELECT"]
