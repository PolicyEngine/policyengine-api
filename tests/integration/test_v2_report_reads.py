"""Read v2 reports, their results and simulations from migrated PostgreSQL.

The routes run as the Public API's runtime role, so the tests prove the
role's declared privileges cover every read (rule
``api.v2.runtime-privileges-tested-as-runtime-role``). The rows are stored as
the simulation service and its Modal workers store them, committed, and
deleted after each test.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

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
from policyengine_api.services.v2.stored_simulations.database_session import (
    StoredSimulationDatabaseSession,
)
from policyengine_api.services.v2.stored_simulations.services import (
    V2StoredSimulationService,
)
from tests.fixtures.economy_results import (
    uk_economy_result,
    uk_local_area_economy_result,
    us_economy_result,
)
from tests.integration.stored_report_rows import (
    LOCAL_AREA_DATASET_NAME,
    REGION_CODES,
    STARTED_AT,
    RunSettings,
    delete_catalog,
    store_catalog,
    store_local_area_catalog,
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
# Two run IDs: of two runs created at the same time, the one with the larger
# ID is the newest, whichever was stored first.
LARGER_RUN_ID = UUID("ffffffff-0000-4000-8000-000000000001")
SMALLER_RUN_ID = UUID("00000000-0000-4000-8000-000000000001")


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
        # On the same versions, the newer run is a forced re-run's.
        newest = store_report_run(
            connection,
            catalog,
            report,
            RunSettings(
                versions=OLDER_VERSIONS,
                created_at=STARTED_AT + timedelta(days=1),
                forced=True,
            ),
            result=output,
        )

    response = client.get(f"/v2/reports/{report.report_id}?country_id={country}")

    assert response.status_code == 200, response.text
    item = response.json()["result"]["item"]
    # A result's model version is the country package version its run used.
    expected = _as_json(output)
    expected["model_version"] = OLDER_VERSIONS["country_package_version"]
    assert item["result"] == expected
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


def test_listing_reads_named_reports_in_the_order_asked(
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
        str(budget_window.report_id),
    ]
    assert [item["kind"] for item in items] == [
        "economy",
        "economy",
        "budget_window",
    ]
    assert [item["status"] for item in items] == ["not_run", "succeeded", "not_run"]
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


def test_of_two_report_runs_created_together_the_larger_id_is_the_newest(
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
                error_message="The worker stopped",
                run_id=LARGER_RUN_ID,
            ),
        )
        store_report_run(
            connection,
            catalog,
            report,
            RunSettings(versions=CURRENT_VERSIONS, run_id=SMALLER_RUN_ID),
            result=us_economy_result(),
        )

    read = client.get(f"/v2/reports/{report.report_id}?country_id=us")
    listed = client.get(f"/v2/reports?country_id=us&report_id={report.report_id}")

    assert read.status_code == 200, read.text
    item = read.json()["result"]["item"]
    assert item["run"]["id"] == str(LARGER_RUN_ID)
    assert item["status"] == "failed"
    assert item["result"] is None
    assert listed.status_code == 200, listed.text
    (summary,) = listed.json()["result"]["items"]
    assert summary["run"]["id"] == str(LARGER_RUN_ID)


def test_of_two_simulation_runs_created_together_the_larger_id_is_the_newest(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    catalog = catalogs["us"]
    with owner_engine.begin() as connection:
        simulation_id = store_simulation(connection, catalog, policy_id=None)
        store_simulation_run(
            connection,
            catalog,
            simulation_id,
            RunSettings(
                versions=CURRENT_VERSIONS, status="pending", run_id=LARGER_RUN_ID
            ),
        )
        store_simulation_run(
            connection,
            catalog,
            simulation_id,
            RunSettings(versions=OLDER_VERSIONS, run_id=SMALLER_RUN_ID),
        )

    response = client.get(f"/v2/simulations/{simulation_id}?country_id=us")

    assert response.status_code == 200, response.text
    item = response.json()["result"]["item"]
    assert item["run"]["id"] == str(LARGER_RUN_ID)
    assert item["status"] == "pending"


DATASET_INDEPENDENT_KEY = "bcabc98b4e0d3eff" * 4


def test_a_search_finds_the_countrys_reports_with_the_key_newest_first(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    with owner_engine.begin() as connection:
        older, newer = (
            store_report(
                connection,
                catalogs["uk"],
                dataset_independent_key=DATASET_INDEPENDENT_KEY,
                created_at=STARTED_AT + timedelta(hours=hours),
            )
            for hours in (1, 2)
        )
        store_report(connection, catalogs["uk"], dataset_independent_key="0" * 64)
        store_report(connection, catalogs["uk"])
        store_report(
            connection, catalogs["us"], dataset_independent_key=DATASET_INDEPENDENT_KEY
        )

    response = client.get(
        f"/v2/reports?country_id=uk&dataset_independent_key={DATASET_INDEPENDENT_KEY}"
    )

    assert response.status_code == 200, response.text
    items = response.json()["result"]["items"]
    assert [item["id"] for item in items] == [
        str(newer.report_id),
        str(older.report_id),
    ]
    assert {item["dataset_independent_key"] for item in items} == {
        DATASET_INDEPENDENT_KEY
    }
    detail = client.get(f"/v2/reports/{newer.report_id}?country_id=uk").json()
    assert detail["result"]["item"]["dataset_independent_key"] == (
        DATASET_INDEPENDENT_KEY
    )


def test_a_local_area_report_reads_its_areas_and_withheld_codes(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    output = uk_local_area_economy_result()
    with owner_engine.begin() as connection:
        local_areas = store_local_area_catalog(connection, catalogs["uk"])
        report = store_report(connection, local_areas)
        store_report_run(
            connection,
            local_areas,
            report,
            RunSettings(versions=CURRENT_VERSIONS),
            result=output,
        )

    response = client.get(f"/v2/reports/{report.report_id}?country_id=uk")

    assert response.status_code == 200, response.text
    item = response.json()["result"]["item"]
    expected = _as_json(output)
    expected["model_version"] = CURRENT_VERSIONS["country_package_version"]
    assert item["data_source"] == "local_area_dataset"
    assert item["region_code"] == "uk"
    assert item["dataset_name"] == LOCAL_AREA_DATASET_NAME
    assert item["result"] == expected


@pytest.mark.parametrize("region_code", ["uk", "country/wales"], ids=["uk", "nation"])
def test_a_uk_wide_or_nation_report_on_its_own_dataset_reads_no_withheld_codes(
    owner_engine: Engine,
    catalogs: dict[str, CatalogRows],
    client: TestClient,
    region_code: str,
) -> None:
    with owner_engine.begin() as connection:
        local_areas = store_local_area_catalog(connection, catalogs["uk"])
        # UK-wide on the national dataset, or the catalog's Wales region.
        on_national_dataset = (
            replace(local_areas, dataset_id=catalogs["uk"].dataset_id)
            if region_code == "uk"
            else catalogs["uk"]
        )
        report = store_report(connection, on_national_dataset)
        store_report_run(
            connection,
            on_national_dataset,
            report,
            RunSettings(versions=CURRENT_VERSIONS),
            result=uk_economy_result(),
        )

    response = client.get(f"/v2/reports/{report.report_id}?country_id=uk")

    assert response.status_code == 200, response.text
    item = response.json()["result"]["item"]
    assert item["data_source"] is None
    assert item["region_code"] == region_code
    assert "constituency_withheld_codes" not in item["result"]
    assert "local_authority_withheld_codes" not in item["result"]


def test_a_local_area_report_with_every_area_of_a_level_withheld_reads_it_empty(
    owner_engine: Engine, catalogs: dict[str, CatalogRows], client: TestClient
) -> None:
    output = {
        **uk_local_area_economy_result(),
        "constituency_impact": [],
        "constituency_withheld_codes": ["E14001063", "W07000081"],
        "local_authority_withheld_codes": [],
    }
    with owner_engine.begin() as connection:
        local_areas = store_local_area_catalog(connection, catalogs["uk"])
        report = store_report(connection, local_areas)
        store_report_run(
            connection,
            local_areas,
            report,
            RunSettings(versions=CURRENT_VERSIONS),
            result=output,
        )

    response = client.get(f"/v2/reports/{report.report_id}?country_id=uk")

    assert response.status_code == 200, response.text
    result = response.json()["result"]["item"]["result"]
    assert result["constituency_impact"] == []
    assert result["constituency_withheld_codes"] == ["E14001063", "W07000081"]
    assert result["local_authority_withheld_codes"] == []
    assert len(result["local_authority_impact"]) == 2
