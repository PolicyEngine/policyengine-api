"""Read v2 reports, their results and simulations from migrated PostgreSQL.

The routes run as the Public API's runtime role, so the tests prove the
role's declared privileges cover every read (rule
``api.v2.runtime-privileges-tested-as-runtime-role``). The rows are stored as
the simulation service and its Modal workers store them, committed, and
deleted after each test.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from flask import Flask
from policyengine_api.services.v2.simulation_service.types import PackageVersions
from policyengine_api.services.v2.stored_reports.database_session import (
    StoredReportDatabaseSession,
)
from policyengine_api.services.v2.stored_reports.services import V2StoredReportService
from policyengine_api.services.v2.stored_simulations.database_session import (
    StoredSimulationDatabaseSession,
)
from policyengine_api.services.v2.stored_simulations.services import (
    V2StoredSimulationService,
)
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
from tests.fixtures.economy_results import uk_economy_result, us_economy_result
from tests.integration.simulation_rows import insert_row
from tests.integration.stored_report_rows import (
    REGION_CODES,
    STARTED_AT,
    RunSettings,
    delete_catalog,
    store_catalog,
    store_report,
    store_report_run,
    store_simulation,
    store_simulation_run,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine

    from tests.integration.stored_report_rows import CatalogRows

CURRENT_VERSIONS = {"country_package_version": "1.5.0", "policyengine_version": "4.2.0"}
OLDER_VERSIONS = {"country_package_version": "1.4.0", "policyengine_version": "4.1.0"}


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
    """Serve the report and simulation routes as the runtime role."""
    runtime_engine = v2_engine_as_role(managed_v2_roles.runtime, poolclass=NullPool)
    sessions = sessionmaker(runtime_engine, class_=Session)
    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        v2_stored_report_service_factory=lambda: V2StoredReportService(
            StoredReportDatabaseSession(sessions), current_versions=current_versions
        ),
        v2_stored_simulation_service_factory=lambda: V2StoredSimulationService(
            StoredSimulationDatabaseSession(sessions),
            current_versions=current_versions,
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


def _as_json(value: Any) -> Any:
    return json.loads(json.dumps(value))


@pytest.mark.parametrize(
    ("country", "output"),
    [("us", us_economy_result()), ("uk", uk_economy_result())],
    ids=["us", "uk"],
)
def test_a_report_reads_its_newest_run_and_that_runs_result(
    owner_engine: Engine,
    catalogs: dict[str, CatalogRows],
    client: TestClient,
    country: str,
    output: dict[str, Any],
) -> None:
    catalog = catalogs[country]
    older_output = json.loads(json.dumps(output))
    older_output["budget"]["tax_revenue_impact"] = 1.0
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
        store_report_run(
            connection,
            catalog,
            report,
            RunSettings(versions=OLDER_VERSIONS),
            result=older_output,
        )
        newest = store_report_run(
            connection,
            catalog,
            report,
            RunSettings(
                versions=OLDER_VERSIONS, created_at=STARTED_AT + timedelta(days=1)
            ),
            result=output,
        )

    response = client.get(f"/v2/reports/{report.report_id}?country_id={country}")

    assert response.status_code == 200, response.text
    item = response.json()["result"]["item"]
    assert item["result"] == _as_json(output)
    assert item["status"] == "succeeded"
    assert item["run"]["id"] == str(newest.report_run_id)
    assert item["run"]["country_package_version"] == "1.4.0"
    assert item["run"]["policyengine_version"] == "4.1.0"
    assert item["run"]["baseline_simulation_run_id"] == str(
        newest.baseline_simulation_run_id
    )
    assert item["current_versions"] == CURRENT_VERSIONS
    assert item["region_code"] == REGION_CODES[country]
    assert item["baseline_simulation"] == {
        "id": str(report.baseline_simulation_id),
        "policy_id": None,
        "dynamic_id": None,
    }
    assert item["reform_simulation"]["policy_id"] == str(catalog.policy_id)
    assert item["options"] == {"include_cliffs": True}
    assert item["kind"] == "economy"


def test_a_newest_run_still_running_has_no_result_even_after_an_older_success(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    catalog = catalogs["us"]
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
        store_report_run(
            connection,
            catalog,
            report,
            RunSettings(versions=OLDER_VERSIONS),
            result=us_economy_result(),
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

    item = client.get(f"/v2/reports/{report.report_id}?country_id=us").json()["result"][
        "item"
    ]

    assert item["status"] == "running"
    assert item["run"]["completed_at"] is None
    assert item["result"] is None


def test_a_failed_newest_run_says_why_without_a_result(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    catalog = catalogs["us"]
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
        store_report_run(
            connection,
            catalog,
            report,
            RunSettings(
                versions=CURRENT_VERSIONS,
                status="failed",
                error_message="simulation_failed: the worker ran out of memory",
            ),
        )

    item = client.get(f"/v2/reports/{report.report_id}?country_id=us").json()["result"][
        "item"
    ]

    assert item["status"] == "failed"
    assert item["run"]["error_message"] == (
        "simulation_failed: the worker ran out of memory"
    )
    assert item["result"] is None


def test_a_report_with_no_run_answers_its_definition(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    catalog = catalogs["uk"]
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)

    response = client.get(f"/v2/reports/{report.report_id}?country_id=uk")

    assert response.status_code == 200
    item = response.json()["result"]["item"]
    assert item["status"] == "not_run"
    assert item["run"] is None
    assert item["result"] is None
    assert item["label"] == "uk reform"
    assert item["year"] == 2026
    assert item["dataset_name"] == "enhanced_frs_2023_24"


def test_a_report_is_not_found_in_another_country(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    with owner_engine.begin() as connection:
        report = store_report(connection, catalogs["us"])

    response = client.get(f"/v2/reports/{report.report_id}?country_id=uk")

    assert response.status_code == 404
    assert response.json()["status"] == "error"


def test_a_succeeded_run_without_result_rows_is_unreadable(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    catalog = catalogs["us"]
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
        store_report_run(
            connection, catalog, report, RunSettings(versions=CURRENT_VERSIONS)
        )

    response = client.get(f"/v2/reports/{report.report_id}?country_id=us")

    assert response.status_code == 500
    assert response.json() == {
        "status": "error",
        "message": "The report's stored result cannot be read",
    }


def test_a_household_report_cannot_be_read_here_yet(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    catalog = catalogs["us"]
    household_id = uuid4()
    with owner_engine.begin() as connection:
        insert_row(
            connection,
            "households",
            id=household_id,
            country_id="us",
            household_data="{}",
            canonicalization_version=1,
            content_hash=uuid4().hex * 2,
        )
        catalog.household_ids.append(household_id)
        report = store_report(connection, catalog, household_id=household_id)

    response = client.get(f"/v2/reports/{report.report_id}?country_id=us")

    assert response.status_code == 422
    assert "household report" in response.json()["message"]


def test_listing_reads_named_economy_reports_in_the_order_asked(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    catalog = catalogs["us"]
    with owner_engine.begin() as connection:
        first = store_report(connection, catalog)
        store_report_run(
            connection,
            catalog,
            first,
            RunSettings(versions=CURRENT_VERSIONS),
            result=us_economy_result(),
        )
        second = store_report(connection, catalog)
        budget_window = store_report(connection, catalog, budget_window_size=3)
        other_country = store_report(connection, catalogs["uk"])
    named = (
        second.report_id,
        uuid4(),
        first.report_id,
        budget_window.report_id,
        other_country.report_id,
        second.report_id,
    )

    response = client.get(
        "/v2/reports?country_id=us&"
        + "&".join(f"report_id={report_id}" for report_id in named)
    )

    assert response.status_code == 200, response.text
    items = response.json()["result"]["items"]
    assert [item["id"] for item in items] == [
        str(second.report_id),
        str(first.report_id),
    ]
    assert [item["status"] for item in items] == ["not_run", "succeeded"]
    assert all("result" not in item for item in items)
    assert items[1]["run"]["country_package_version"] == "1.5.0"


def test_a_simulation_reads_its_newest_run_in_its_country(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    catalog = catalogs["uk"]
    with owner_engine.begin() as connection:
        simulation_id = store_simulation(
            connection, catalog, policy_id=catalog.policy_id
        )
        store_simulation_run(
            connection, catalog, simulation_id, RunSettings(versions=OLDER_VERSIONS)
        )
        newest_run_id = store_simulation_run(
            connection,
            catalog,
            simulation_id,
            RunSettings(
                versions=CURRENT_VERSIONS,
                status="pending",
                created_at=STARTED_AT + timedelta(hours=1),
            ),
        )

    response = client.get(f"/v2/simulations/{simulation_id}?country_id=uk")
    elsewhere = client.get(f"/v2/simulations/{simulation_id}?country_id=us")

    assert response.status_code == 200, response.text
    item = response.json()["result"]["item"]
    assert item["id"] == str(simulation_id)
    assert item["country_id"] == "uk"
    assert item["kind"] == "economy"
    assert item["policy_id"] == str(catalog.policy_id)
    assert item["region_code"] == "country/wales"
    assert item["dataset_name"] == "enhanced_frs_2023_24"
    assert item["status"] == "pending"
    assert item["run"]["id"] == str(newest_run_id)
    assert item["run"]["policyengine_version"] == "4.2.0"
    assert item["current_versions"] == CURRENT_VERSIONS
    assert elsewhere.status_code == 404


def test_a_simulation_with_no_run_answers_its_definition(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    catalog = catalogs["us"]
    with owner_engine.begin() as connection:
        simulation_id = store_simulation(connection, catalog, policy_id=None)

    item = client.get(f"/v2/simulations/{simulation_id}?country_id=us").json()[
        "result"
    ]["item"]

    assert item["status"] == "not_run"
    assert item["run"] is None
    assert item["policy_id"] is None
    assert item["year"] == 2026
