"""Create, read and list household reports through /v2/reports on migrated PostgreSQL.

The routes run as the Public API's runtime role, so the tests prove its
declared privileges cover every read: the countries row, the stored household
and policies the checks read, and the reports, simulations, runs and
calculated households the reads return (rule
``api.v2.runtime-privileges-tested-as-runtime-role``). The rows the
simulation service and its household functions write are stored by the
disposable database's owner, committed, and deleted after each test. The UK
is made household-only for each test and restored afterwards.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

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
from policyengine_api.services.v2.countries.database_session import (
    CountryDatabaseSession,
)
from policyengine_api.services.v2.countries.services import V2CountryService
from policyengine_api.services.v2.households.database_session import (
    HouseholdDatabaseSession,
)
from policyengine_api.services.v2.households.services import V2HouseholdService
from policyengine_api.services.v2.policies.database_session import (
    PolicyDatabaseSession,
)
from policyengine_api.services.v2.policies.services import V2PolicyService
from policyengine_api.services.v2.simulation_service.services import (
    SimulationSubmissionService,
)
from policyengine_api.services.v2.simulation_service.types import (
    PackageVersions,
    SubmittedReport,
)
from policyengine_api.services.v2.stored_reports.database_session import (
    StoredReportDatabaseSession,
)
from policyengine_api.services.v2.stored_reports.services import V2StoredReportService
from tests.integration.simulation_rows import insert_row
from tests.integration.stored_report_rows import (
    STARTED_AT,
    delete_catalog,
    store_catalog,
    store_report,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Connection, Engine

    from policyengine_api.services.v2.simulation_service.types import (
        HouseholdReportCreationInput,
    )
    from tests.integration.stored_report_rows import CatalogRows

CURRENT_VERSIONS = {"country_package_version": "1.5.0", "policyengine_version": "4.2.0"}
STORED_HOUSEHOLD = {"people": {"you": {"age": {"2026": 40}}}}
BASELINE_HOUSEHOLD = {
    "people": {"you": {"age": {"2026": 40}, "net_income": {"2026": 30000.0}}}
}
REFORM_HOUSEHOLD = {
    "people": {"you": {"age": {"2026": 40}, "net_income": {"2026": 31250.5}}}
}


def current_versions(country_id: str) -> PackageVersions:
    return PackageVersions(**CURRENT_VERSIONS)


def succeeded_document(household: dict[str, Any]) -> dict[str, Any]:
    """Return the household function's result document for a calculated household."""
    return {
        "status": "succeeded",
        "schema_version": 1,
        "output": {
            "household": household,
            "warnings": [],
            "spm_config": None,
            "spm_provenance": None,
        },
    }


@dataclass(frozen=True)
class StoredHouseholdReport:
    """A stored household report and its newest run's IDs."""

    report_id: UUID
    report_run_id: UUID


def store_household(connection: Connection, catalog: CatalogRows) -> UUID:
    """Store a household in the catalog's country; ``delete_catalog`` removes it."""
    household_id = uuid4()
    insert_row(
        connection,
        "households",
        id=household_id,
        country_id=catalog.country,
        default_year=2026,
        household_data=json.dumps(STORED_HOUSEHOLD),
        canonicalization_version=1,
        content_hash=uuid4().hex * 2,
    )
    catalog.household_ids.append(household_id)
    return household_id


@dataclass(frozen=True)
class SimulationRunToStore:
    """A household simulation's run: its status and calculated household's document."""

    status: str
    document: dict[str, Any] | None

    @property
    def finished(self) -> bool:
        return self.status in {"succeeded", "failed"}


def store_household_simulation(
    connection: Connection,
    catalog: CatalogRows,
    household_id: UUID,
    *,
    policy_id: UUID | None,
    run: SimulationRunToStore,
) -> tuple[UUID, UUID]:
    """Store a household simulation and one run; return both IDs."""
    simulation_id = uuid4()
    insert_row(
        connection,
        "simulations",
        id=simulation_id,
        simulation_type="household",
        household_id=household_id,
        policy_id=policy_id,
        tax_benefit_model_version_id=catalog.version_id,
        year=2026,
    )
    catalog.simulation_ids.append(simulation_id)
    run_id = uuid4()
    insert_row(
        connection,
        "simulation_runs",
        id=run_id,
        simulation_id=simulation_id,
        year=2026,
        tax_benefit_model_version_id=catalog.version_id,
        status=run.status,
        started_at=STARTED_AT,
        completed_at=STARTED_AT + timedelta(minutes=1) if run.finished else None,
        household_result=None if run.document is None else json.dumps(run.document),
        **CURRENT_VERSIONS,
    )
    return simulation_id, run_id


def store_household_report(
    connection: Connection,
    catalog: CatalogRows,
    household_id: UUID,
    *,
    status: str = "succeeded",
) -> StoredHouseholdReport:
    """Store a household report of current law and the catalog's policy, with a run.

    A succeeded run's simulation runs hold their calculated households.
    """
    succeeded = status == "succeeded"
    baseline_id, baseline_run_id = store_household_simulation(
        connection,
        catalog,
        household_id,
        policy_id=None,
        run=SimulationRunToStore(
            status, succeeded_document(BASELINE_HOUSEHOLD) if succeeded else None
        ),
    )
    reform_id, reform_run_id = store_household_simulation(
        connection,
        catalog,
        household_id,
        policy_id=catalog.policy_id,
        run=SimulationRunToStore(
            status, succeeded_document(REFORM_HOUSEHOLD) if succeeded else None
        ),
    )
    report_id = uuid4()
    insert_row(
        connection,
        "reports",
        id=report_id,
        label="My household under the reform",
        country=catalog.country,
        tax_benefit_model_id=catalog.model_id,
        policy_id=catalog.policy_id,
        baseline_simulation_id=baseline_id,
        reform_simulation_id=reform_id,
        household_id=household_id,
        year=2026,
        inputs=json.dumps({"add_missing_variables": True}),
    )
    catalog.report_ids.append(report_id)
    report_run_id = uuid4()
    insert_row(
        connection,
        "report_runs",
        id=report_run_id,
        report_id=report_id,
        baseline_simulation_run_id=baseline_run_id,
        reform_simulation_run_id=reform_run_id,
        status=status,
        trigger="initial",
        started_at=STARTED_AT,
        completed_at=(
            STARTED_AT + timedelta(minutes=1)
            if status in {"succeeded", "failed"}
            else None
        ),
        **CURRENT_VERSIONS,
    )
    return StoredHouseholdReport(report_id=report_id, report_run_id=report_run_id)


@dataclass
class StoringHouseholdReportService:
    """Store what the simulation service would create for a household report."""

    engine: Engine
    catalog: CatalogRows
    household_reports: list[HouseholdReportCreationInput] = field(default_factory=list)

    def submit_household_report(
        self, report: HouseholdReportCreationInput
    ) -> SubmittedReport:
        self.household_reports.append(report)
        with self.engine.begin() as connection:
            stored = store_household_report(
                connection, self.catalog, report.household_id, status="pending"
            )
        return SubmittedReport(
            report_id=stored.report_id, report_run_id=stored.report_run_id
        )


@pytest.fixture
def owner_engine(disposable_v2_database_url: str) -> Iterator[Engine]:
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    engine = create_engine(disposable_v2_database_url, poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture
def household_only_uk(owner_engine: Engine) -> Iterator[CatalogRows]:
    """Make the UK household-only, store a UK catalog, and restore both after."""
    with owner_engine.begin() as connection:
        connection.execute(
            text("UPDATE countries SET society_wide_enabled = false WHERE id = 'uk'")
        )
        catalog = store_catalog(connection, "uk")
    try:
        yield catalog
    finally:
        # Each in its own transaction, so a failed cleanup still restores the UK.
        with owner_engine.begin() as connection:
            connection.execute(
                text("UPDATE countries SET society_wide_enabled = true WHERE id = 'uk'")
            )
        with owner_engine.begin() as connection:
            delete_catalog(connection, catalog)


@pytest.fixture
def runtime_sessions(managed_v2_roles, v2_engine_as_role) -> Iterator[Any]:
    engine = v2_engine_as_role(managed_v2_roles.runtime, poolclass=NullPool)
    yield sessionmaker(engine, class_=Session)
    engine.dispose()


def client_for(
    sessions: Any, simulation_service: StoringHouseholdReportService | None = None
) -> TestClient:
    """Serve the report routes as the runtime role, creating through the stand-in."""
    submissions = SimulationSubmissionService(
        countries=V2CountryService(CountryDatabaseSession(sessions)),
        households=V2HouseholdService(HouseholdDatabaseSession(sessions)),
        policies=V2PolicyService(
            PolicyDatabaseSession(sessions), running_policyengine_version="4.2.0"
        ),
        client_factory=lambda: simulation_service,
    )
    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        v2_stored_report_service_factory=lambda: V2StoredReportService(
            StoredReportDatabaseSession(sessions),
            current_versions=current_versions,
            submissions=submissions,
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


def household_body(household_id: UUID, policy_id: UUID) -> dict[str, Any]:
    return {
        "country_id": "uk",
        "kind": "household",
        "label": "My household under the reform",
        "household_id": str(household_id),
        "year": 2026,
        "baseline": {},
        "reform": {"policy_id": str(policy_id)},
        "add_missing_variables": True,
    }


def test_a_household_report_answers_both_calculated_households(
    owner_engine: Engine, household_only_uk: CatalogRows, runtime_sessions: Any
) -> None:
    catalog = household_only_uk
    with owner_engine.begin() as connection:
        household_id = store_household(connection, catalog)
        stored = store_household_report(connection, catalog, household_id)

    response = client_for(runtime_sessions).get(
        f"/v2/reports/{stored.report_id}?country_id=uk"
    )

    assert response.status_code == 200, response.text
    item = response.json()["result"]["item"]
    assert item["kind"] == "household"
    assert item["household_id"] == str(household_id)
    assert item["options"] == {"add_missing_variables": True}
    assert item["status"] == "succeeded"
    assert item["run"]["id"] == str(stored.report_run_id)
    assert item["reform_simulation"]["policy_id"] == str(catalog.policy_id)
    assert item["result"]["baseline"]["household"] == BASELINE_HOUSEHOLD
    assert item["result"]["reform"]["household"] == REFORM_HOUSEHOLD


def test_household_reports_are_listed_beside_economy_reports(
    owner_engine: Engine, household_only_uk: CatalogRows, runtime_sessions: Any
) -> None:
    catalog = household_only_uk
    with owner_engine.begin() as connection:
        household_id = store_household(connection, catalog)
        household_report = store_household_report(
            connection, catalog, household_id, status="running"
        )
        economy_report = store_report(connection, catalog)

    response = client_for(runtime_sessions).get(
        "/v2/reports?country_id=uk"
        f"&report_id={economy_report.report_id}"
        f"&report_id={household_report.report_id}"
    )

    assert response.status_code == 200, response.text
    items = response.json()["result"]["items"]
    assert [(item["id"], item["kind"]) for item in items] == [
        (str(economy_report.report_id), "economy"),
        (str(household_report.report_id), "household"),
    ]
    assert items[1]["status"] == "running"
    assert all("result" not in item for item in items)


def test_a_household_only_country_creates_a_household_report(
    owner_engine: Engine, household_only_uk: CatalogRows, runtime_sessions: Any
) -> None:
    catalog = household_only_uk
    with owner_engine.begin() as connection:
        household_id = store_household(connection, catalog)
    simulation_service = StoringHouseholdReportService(owner_engine, catalog)

    response = client_for(runtime_sessions, simulation_service).post(
        "/v2/reports?country_id=uk",
        json=household_body(household_id, catalog.policy_id),
    )

    assert response.status_code == 201, response.text
    item = response.json()["result"]["item"]
    assert item["id"] == str(catalog.report_ids[0])
    assert item["kind"] == "household"
    assert item["status"] == "pending"
    assert item["result"] is None
    (sent,) = simulation_service.household_reports
    assert sent.household_id == household_id
    assert sent.add_missing_variables is True


def test_a_household_the_country_does_not_store_is_not_sent(
    owner_engine: Engine, household_only_uk: CatalogRows, runtime_sessions: Any
) -> None:
    simulation_service = StoringHouseholdReportService(owner_engine, household_only_uk)

    response = client_for(runtime_sessions, simulation_service).post(
        "/v2/reports?country_id=uk",
        json=household_body(uuid4(), household_only_uk.policy_id),
    )

    assert response.status_code == 404
    assert simulation_service.household_reports == []


def test_a_household_only_country_still_refuses_economy_reports(
    household_only_uk: CatalogRows, runtime_sessions: Any
) -> None:
    response = client_for(runtime_sessions).post(
        "/v2/reports?country_id=uk",
        json={
            "country_id": "uk",
            "kind": "economy",
            "label": "Economy",
            "year": 2026,
            "region_code": "country/wales",
            "baseline": {},
            "reform": {},
        },
    )

    assert response.status_code == 422
    assert "Economy calculations are not available" in response.json()["message"]
