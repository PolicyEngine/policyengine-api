"""Read a v2 report's cliffs from its simulation runs' cliff calculations.

The routes run as the Public API's runtime role, so the tests prove its
``SELECT`` on ``cliff_impacts`` covers the read (rule
``api.v2.runtime-privileges-tested-as-runtime-role``). The simulation
service inserts a run's cliff calculations and its Modal worker finishes
them; here the database owner stores them, commits them, and the catalog's
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
from sqlalchemy import create_engine, text
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
from tests.fixtures.economy_results import uk_economy_result, us_economy_result
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
    from collections.abc import Iterator

    from sqlalchemy import Engine

    from tests.integration.stored_report_rows import CatalogRows

CURRENT_VERSIONS = {"country_package_version": "1.5.0", "policyengine_version": "4.2.0"}
FAILURE = "cliff_calculation_failed: the calculation raised an error"


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


def read_report(client: TestClient, report_id: object, country: str) -> Any:
    response = client.get(f"/v2/reports/{report_id}?country_id={country}")
    assert response.status_code == 200, response.text
    return response.json()["result"]["item"]


def test_a_succeeded_run_reads_its_simulation_runs_cliff_results(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    catalog = catalogs["us"]
    output = us_economy_result()
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
        # The result's cliff impact is stored as each simulation run's
        # succeeded cliff calculation.
        store_report_run(
            connection,
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
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    catalog = catalogs["uk"]
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
        run_ids = store_report_run(
            connection,
            catalog,
            report,
            RunSettings(versions=CURRENT_VERSIONS),
            result=uk_economy_result(),
        )
        # As the report run writer stores a result that has cliffs.
        connection.execute(
            text(
                "UPDATE report_runs SET baseline_cliff_gap = 1.0, "
                "baseline_cliff_share = 0.1, reform_cliff_gap = 2.0, "
                "reform_cliff_share = 0.2 WHERE id = :id"
            ),
            {"id": run_ids.report_run_id},
        )

    item = read_report(client, report.report_id, "uk")

    assert item["status"] == "succeeded"
    assert item["result"]["cliff_impact"] is None
    assert item["cliffs"]["status"] == "not_calculated"


def test_a_run_still_calculating_reads_each_sides_cliff_progress(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    catalog = catalogs["us"]
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
        run_ids = store_report_run(
            connection,
            catalog,
            report,
            RunSettings(versions=CURRENT_VERSIONS, status="running"),
        )
        store_cliff_calculation(
            connection, run_ids.baseline_simulation_run_id, "running"
        )
        # A failed calculation never counts: the newer pending one is read.
        store_cliff_calculation(
            connection,
            run_ids.reform_simulation_run_id,
            "failed",
            error_message=FAILURE,
        )
        store_cliff_calculation(
            connection,
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
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    catalog = catalogs["uk"]
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
        run_ids = store_report_run(
            connection,
            catalog,
            report,
            RunSettings(versions=CURRENT_VERSIONS),
            result=uk_economy_result(),
        )
        store_cliff_calculation(
            connection,
            run_ids.baseline_simulation_run_id,
            "succeeded",
            cliff_gap=1_000_000.0,
            cliff_share=0.02,
        )
        store_cliff_calculation(
            connection,
            run_ids.reform_simulation_run_id,
            "failed",
            error_message="modal_call_ended: the call ended without a result",
        )
        store_cliff_calculation(
            connection,
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
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    with owner_engine.begin() as connection:
        report = store_report(connection, catalogs["us"])

    item = read_report(client, report.report_id, "us")

    assert item["status"] == "not_run"
    assert item["cliffs"] is None
