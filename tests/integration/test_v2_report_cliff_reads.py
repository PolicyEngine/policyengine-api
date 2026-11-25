"""Read a v2 report's cliffs from its simulation runs' cliff calculations.

The routes run as API v1's runtime role, so the tests prove its ``SELECT`` on
``cliff_impacts`` covers the read (rule
``api.v2.runtime-privileges-tested-as-runtime-role``). The database owner
stores each run's cliff calculations here, commits them, and the catalog's
deletion removes them with their runs.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from flask import Flask

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
from tests.fixtures.database_sessions import recorded_statements
from tests.fixtures.economy_results import uk_economy_result, us_economy_result
from tests.integration.privilege_statements import (
    REPORT_RUN_CLIFF_COLUMNS,
    ReportRunColumns,
    update_row,
)
from tests.integration.stored_report_rows import (
    STARTED_AT,
    RunSettings,
    delete_catalog,
    store_catalog,
    store_cliff_calculation,
    store_report,
    store_report_run,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

    from tests.integration.conftest import ManagedV2Roles
    from tests.integration.stored_report_rows import CatalogRows

CURRENT_VERSIONS = {"country_package_version": "1.5.0", "policyengine_version": "4.2.0"}
FAILURE = "cliff_calculation_failed: the calculation raised an error"


def current_versions(country_id: str) -> PackageVersions:
    return PackageVersions(**CURRENT_VERSIONS)


@pytest.fixture
def owner_sessions(
    v2_owner_sessions: sessionmaker[Session],
) -> sessionmaker[Session]:
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    return v2_owner_sessions


@pytest.fixture
def catalogs(
    owner_sessions: sessionmaker[Session],
) -> Iterator[dict[str, CatalogRows]]:
    """Store a US and a UK catalog, and delete them and their reports after."""
    with owner_sessions.begin() as session:
        stored = {country: store_catalog(session, country) for country in ("us", "uk")}
    yield stored
    with owner_sessions.begin() as session:
        for catalog in stored.values():
            delete_catalog(session, catalog)


@pytest.fixture
def runtime_sessions(
    managed_v2_roles: ManagedV2Roles,
    v2_sessions_as_role: Callable[[str], sessionmaker[Session]],
) -> sessionmaker[Session]:
    return v2_sessions_as_role(managed_v2_roles.runtime)


@pytest.fixture
def client(runtime_sessions: sessionmaker[Session]) -> TestClient:
    """Serve the report routes as the runtime role."""
    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        v2_stored_report_service_factory=lambda: V2StoredReportService(
            StoredReportDatabaseSession(runtime_sessions),
            current_versions=current_versions,
        ),
    )
    settings = RouteImplementationSettings(
        health=RouteImplementation.FLASK_FALLBACK,
        specification=RouteImplementation.FLASK_FALLBACK,
        metadata=RouteImplementation.FLASK_FALLBACK,
    )
    return TestClient(
        create_asgi_app(
            Flask(__name__), dependencies=dependencies, route_settings=settings
        )
    )


def read_report(client: TestClient, report_id: object, country: str) -> Any:
    response = client.get(f"/v2/reports/{report_id}?country_id={country}")
    assert response.status_code == 200, response.text
    return response.json()["result"]["item"]


def test_a_succeeded_run_reads_its_simulation_runs_cliff_results(
    owner_sessions: sessionmaker[Session],
    catalogs: dict[str, CatalogRows],
    client: TestClient,
) -> None:
    catalog = catalogs["us"]
    output = us_economy_result()
    with owner_sessions.begin() as session:
        report = store_report(session, catalog)
        # The result's cliff impact is stored as each simulation run's
        # succeeded cliff calculation.
        store_report_run(
            session,
            catalog,
            report,
            RunSettings(versions=CURRENT_VERSIONS),
            result=output,
        )

    item = read_report(client, report.report_id, "us")

    assert item["result"]["cliff_impact"] == json.loads(
        json.dumps(output["cliff_impact"])
    )
    assert item["cliffs"] == {
        "status": "succeeded",
        "baseline": {"status": "succeeded", "error_message": None},
        "reform": {"status": "succeeded", "error_message": None},
    }


def test_a_report_runs_own_cliff_columns_are_not_read(
    owner_sessions: sessionmaker[Session],
    catalogs: dict[str, CatalogRows],
    client: TestClient,
) -> None:
    catalog = catalogs["uk"]
    with owner_sessions.begin() as session:
        report = store_report(session, catalog)
        run_ids = store_report_run(
            session,
            catalog,
            report,
            RunSettings(versions=CURRENT_VERSIONS),
            result=uk_economy_result(),
        )
        # The report run's own columns hold cliffs; its simulation runs have
        # none. ReportRun's mapper leaves these columns out, so they are set
        # through ReportRunColumns.
        session.execute(
            update_row(
                ReportRunColumns,
                run_ids.report_run_id,
                baseline_cliff_gap=1.0,
                baseline_cliff_share=0.1,
                reform_cliff_gap=2.0,
                reform_cliff_share=0.2,
            )
        )

    item = read_report(client, report.report_id, "uk")

    assert item["status"] == "succeeded"
    assert item["result"]["cliff_impact"] is None
    assert item["cliffs"]["status"] == "not_calculated"


def test_reading_a_report_and_its_runs_names_no_report_run_cliff_column(
    owner_sessions: sessionmaker[Session],
    catalogs: dict[str, CatalogRows],
    client: TestClient,
    runtime_sessions: sessionmaker[Session],
) -> None:
    """No statement the read sends names a report run's own cliff columns."""
    with owner_sessions.begin() as session:
        report = store_report(session, catalogs["us"])
        store_report_run(
            session,
            catalogs["us"],
            report,
            RunSettings(versions=CURRENT_VERSIONS),
            result=us_economy_result(),
        )

    with recorded_statements(runtime_sessions) as runtime_statements:
        read_report(client, report.report_id, "us")
        runs = client.get(f"/v2/reports/{report.report_id}/runs?country_id=us")

    assert runs.status_code == 200, runs.text
    report_run_loads = [
        statement for statement in runtime_statements if "report_runs" in statement
    ]
    assert report_run_loads
    assert [
        column
        for column in REPORT_RUN_CLIFF_COLUMNS
        if any(column in statement for statement in report_run_loads)
    ] == []


def test_a_run_still_calculating_reads_each_sides_cliff_progress(
    owner_sessions: sessionmaker[Session],
    catalogs: dict[str, CatalogRows],
    client: TestClient,
) -> None:
    catalog = catalogs["us"]
    with owner_sessions.begin() as session:
        report = store_report(session, catalog)
        run_ids = store_report_run(
            session,
            catalog,
            report,
            RunSettings(versions=CURRENT_VERSIONS, status="running"),
        )
        store_cliff_calculation(session, run_ids.baseline_simulation_run_id, "running")
        # A failed calculation never counts: the newer pending one is read.
        store_cliff_calculation(
            session,
            run_ids.reform_simulation_run_id,
            "failed",
            error_message=FAILURE,
        )
        store_cliff_calculation(
            session,
            run_ids.reform_simulation_run_id,
            "pending",
            created_at=STARTED_AT + timedelta(minutes=5),
        )

    item = read_report(client, report.report_id, "us")

    assert item["result"] is None
    assert item["cliffs"] == {
        "status": "running",
        "baseline": {"status": "running", "error_message": None},
        "reform": {"status": "pending", "error_message": None},
    }


def test_a_side_whose_calculations_all_failed_says_why_the_newest_failed(
    owner_sessions: sessionmaker[Session],
    catalogs: dict[str, CatalogRows],
    client: TestClient,
) -> None:
    catalog = catalogs["uk"]
    with owner_sessions.begin() as session:
        report = store_report(session, catalog)
        run_ids = store_report_run(
            session,
            catalog,
            report,
            RunSettings(versions=CURRENT_VERSIONS),
            result=uk_economy_result(),
        )
        store_cliff_calculation(
            session,
            run_ids.baseline_simulation_run_id,
            "succeeded",
            cliff_gap=1_000_000.0,
            cliff_share=0.02,
        )
        store_cliff_calculation(
            session,
            run_ids.reform_simulation_run_id,
            "failed",
            error_message="modal_call_ended: the call ended without a result",
        )
        store_cliff_calculation(
            session,
            run_ids.reform_simulation_run_id,
            "failed",
            created_at=STARTED_AT + timedelta(minutes=5),
            error_message=FAILURE,
        )

    item = read_report(client, report.report_id, "uk")

    assert item["result"]["cliff_impact"] is None
    assert item["cliffs"] == {
        "status": "failed",
        "baseline": {"status": "succeeded", "error_message": None},
        "reform": {"status": "failed", "error_message": FAILURE},
    }


def test_a_report_with_no_run_reads_no_cliffs(
    owner_sessions: sessionmaker[Session],
    catalogs: dict[str, CatalogRows],
    client: TestClient,
) -> None:
    with owner_sessions.begin() as session:
        report = store_report(session, catalogs["us"])

    item = read_report(client, report.report_id, "us")

    assert item["status"] == "not_run"
    assert item["cliffs"] is None
