"""Read a v2 report with the run a caller names, on migrated PostgreSQL.

``GET /v2/reports/{report_id}?run_id=`` answers that run of the report, its
status, versions and result, whichever run is the newest: a report run of an
economy or household report, or a budget-window run of a budget window. The
routes run as the Public API's runtime role.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from flask import Flask
from sqlalchemy import create_engine
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
from tests.fixtures.economy_results import us_economy_result
from tests.integration.simulation_rows import insert_row
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

    from sqlalchemy import Engine

    from tests.integration.stored_report_rows import CatalogRows

CURRENT_VERSIONS = {"country_package_version": "1.5.0", "policyengine_version": "4.2.0"}
OLDER_VERSIONS = {"country_package_version": "1.4.0", "policyengine_version": "4.1.0"}
WINDOW_YEARS = (2026, 2027)


def current_versions(country_id: str) -> PackageVersions:
    return PackageVersions(**CURRENT_VERSIONS)


@pytest.fixture
def owner_engine(disposable_v2_database_url: str) -> Iterator[Engine]:
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    engine = create_engine(disposable_v2_database_url, poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture
def catalog(owner_engine: Engine) -> Iterator[CatalogRows]:
    with owner_engine.begin() as connection:
        stored = store_catalog(connection, "us")
    yield stored
    with owner_engine.begin() as connection:
        delete_catalog(connection, stored)


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


def test_an_economy_report_is_read_with_the_run_named_rather_than_its_newest(
    owner_engine: Engine, catalog: CatalogRows, client: TestClient
) -> None:
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
        named = store_report_run(
            connection,
            catalog,
            report,
            RunSettings(versions=OLDER_VERSIONS, status="succeeded"),
            result=us_economy_result(),
        )
        newest = store_report_run(
            connection,
            catalog,
            report,
            RunSettings(
                versions=CURRENT_VERSIONS,
                status="running",
                created_at=STARTED_AT + timedelta(days=1),
            ),
        )

    named_read = client.get(
        f"/v2/reports/{report.report_id}?country_id=us&run_id={named.report_run_id}"
    )
    newest_read = client.get(
        f"/v2/reports/{report.report_id}?country_id=us&run_id={newest.report_run_id}"
    )

    assert named_read.status_code == 200, named_read.text
    item = named_read.json()["result"]["item"]
    assert item["status"] == "succeeded"
    assert item["run"]["id"] == str(named.report_run_id)
    assert item["run"]["policyengine_version"] == "4.1.0"
    assert item["result"] is not None
    assert newest_read.status_code == 200, newest_read.text
    newest_item = newest_read.json()["result"]["item"]
    assert newest_item["run"]["id"] == str(newest.report_run_id)
    assert newest_item["status"] == "running"
    assert newest_item["result"] is None


def test_a_run_that_is_not_one_of_the_reports_own_is_not_found(
    owner_engine: Engine, catalog: CatalogRows, client: TestClient
) -> None:
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
        store_report_run(connection, catalog, report, RunSettings(CURRENT_VERSIONS))
        other_report = store_report(connection, catalog)
        other_run = store_report_run(
            connection, catalog, other_report, RunSettings(CURRENT_VERSIONS)
        )
        window = store_report(connection, catalog, budget_window_size=2)
        window_run_id = store_budget_window_run(
            connection, catalog, window, RunSettings(CURRENT_VERSIONS)
        )
        year_run = store_report_run(
            connection,
            catalog,
            store_year_simulations(connection, catalog, window, WINDOW_YEARS[0]),
            RunSettings(
                CURRENT_VERSIONS,
                budget_window_year=BudgetWindowYear(
                    budget_window_run_id=window_run_id, year=WINDOW_YEARS[0]
                ),
            ),
        )

    another_reports_run = client.get(
        f"/v2/reports/{report.report_id}?country_id=us&run_id={other_run.report_run_id}"
    )
    unknown_run = client.get(
        f"/v2/reports/{report.report_id}?country_id=us&run_id={uuid4()}"
    )
    window_year_run = client.get(
        f"/v2/reports/{window.report_id}?country_id=us&run_id={year_run.report_run_id}"
    )
    window_run_of_an_economy_report = client.get(
        f"/v2/reports/{report.report_id}?country_id=us&run_id={window_run_id}"
    )

    for response in (
        another_reports_run,
        unknown_run,
        window_year_run,
        window_run_of_an_economy_report,
    ):
        assert response.status_code == 404, response.text
        assert "run" in response.json()["message"]


def test_a_budget_window_is_read_with_the_window_run_named_and_its_years(
    owner_engine: Engine, catalog: CatalogRows, client: TestClient
) -> None:
    with owner_engine.begin() as connection:
        window = store_report(connection, catalog, budget_window_size=2)
        window_run_ids = []
        for days_later, status in ((0, "failed"), (1, "pending")):
            settings = RunSettings(
                versions=CURRENT_VERSIONS,
                status=status,
                created_at=STARTED_AT + timedelta(days=days_later),
            )
            window_run_id = store_budget_window_run(
                connection, catalog, window, settings
            )
            window_run_ids.append(window_run_id)
            for year in WINDOW_YEARS:
                store_report_run(
                    connection,
                    catalog,
                    store_year_simulations(connection, catalog, window, year),
                    RunSettings(
                        versions=CURRENT_VERSIONS,
                        status=status,
                        created_at=settings.created_at,
                        budget_window_year=BudgetWindowYear(
                            budget_window_run_id=window_run_id, year=year
                        ),
                    ),
                )
    older_window_run_id = window_run_ids[0]

    response = client.get(
        f"/v2/reports/{window.report_id}?country_id=us&run_id={older_window_run_id}"
    )

    assert response.status_code == 200, response.text
    item = response.json()["result"]["item"]
    assert item["kind"] == "budget_window"
    assert item["run"]["id"] == str(older_window_run_id)
    assert item["status"] == "failed"
    assert [year["year"] for year in item["run"]["years"]] == list(WINDOW_YEARS)
    assert {year["status"] for year in item["run"]["years"]} == {"failed"}


def test_a_household_report_is_read_with_the_run_named(
    owner_engine: Engine, catalog: CatalogRows, client: TestClient
) -> None:
    with owner_engine.begin() as connection:
        household_id = uuid4()
        insert_row(
            connection,
            "households",
            id=household_id,
            country_id=catalog.country,
            household_data="{}",
            canonicalization_version=1,
            content_hash=uuid4().hex * 2,
        )
        catalog.household_ids.append(household_id)
        report = store_report(connection, catalog, household_id=household_id)
        named = store_report_run(
            connection,
            catalog,
            report,
            RunSettings(versions=OLDER_VERSIONS, status="pending"),
        )
        store_report_run(
            connection,
            catalog,
            report,
            RunSettings(
                versions=CURRENT_VERSIONS,
                status="running",
                created_at=STARTED_AT + timedelta(days=1),
            ),
        )

    response = client.get(
        f"/v2/reports/{report.report_id}?country_id=us&run_id={named.report_run_id}"
    )

    assert response.status_code == 200, response.text
    item = response.json()["result"]["item"]
    assert item["kind"] == "household"
    assert item["run"]["id"] == str(named.report_run_id)
    assert item["status"] == "pending"
