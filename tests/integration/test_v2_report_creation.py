"""Create v2 reports and simulations, then read them back from migrated PostgreSQL.

A stand-in for the simulation service's client stores the rows the
simulation service would create and answers with their IDs; the routes run
as the Public API's runtime role, checking the country and policies and
reading the created records back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    SubmittedSimulation,
)
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
from tests.integration.stored_report_rows import (
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

    from policyengine_api.services.v2.simulation_service.types import (
        EconomyReportCreationInput,
        EconomySimulationCreationInput,
    )
    from tests.integration.stored_report_rows import CatalogRows

CURRENT_VERSIONS = {"country_package_version": "1.5.0", "policyengine_version": "4.2.0"}


def current_versions(country_id: str) -> PackageVersions:
    return PackageVersions(**CURRENT_VERSIONS)


@dataclass
class StoringSimulationService:
    """Store what the simulation service would create, and answer with its IDs.

    With ``answer_unstored``, it answers with IDs it stored nothing for, and
    keeps them in ``unstored_ids``.
    """

    engine: Engine
    catalog: CatalogRows
    answer_unstored: bool = False
    reports: list[EconomyReportCreationInput] = field(default_factory=list)
    simulations: list[EconomySimulationCreationInput] = field(default_factory=list)
    unstored_ids: list[UUID] = field(default_factory=list)

    def submit_report(self, report: EconomyReportCreationInput) -> SubmittedReport:
        self.reports.append(report)
        if self.answer_unstored:
            self.unstored_ids.append(uuid4())
            return SubmittedReport(
                report_id=self.unstored_ids[-1], report_run_id=uuid4()
            )
        with self.engine.begin() as connection:
            stored = store_report(connection, self.catalog)
            run_ids = store_report_run(
                connection,
                self.catalog,
                stored,
                RunSettings(versions=CURRENT_VERSIONS, status="pending"),
            )
        return SubmittedReport(
            report_id=stored.report_id, report_run_id=run_ids.report_run_id
        )

    def submit_simulation(
        self, simulation: EconomySimulationCreationInput
    ) -> SubmittedSimulation:
        self.simulations.append(simulation)
        if self.answer_unstored:
            self.unstored_ids.append(uuid4())
            return SubmittedSimulation(
                simulation_id=self.unstored_ids[-1], simulation_run_id=uuid4()
            )
        with self.engine.begin() as connection:
            simulation_id = store_simulation(
                connection, self.catalog, policy_id=simulation.policy_id
            )
            run_id = store_simulation_run(
                connection,
                self.catalog,
                simulation_id,
                RunSettings(versions=CURRENT_VERSIONS, status="pending"),
            )
        return SubmittedSimulation(
            simulation_id=simulation_id, simulation_run_id=run_id
        )


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
def runtime_sessions(managed_v2_roles, v2_engine_as_role) -> Iterator[Any]:
    engine = v2_engine_as_role(managed_v2_roles.runtime, poolclass=NullPool)
    yield sessionmaker(engine, class_=Session)
    engine.dispose()


def client_for(
    sessions: Any, simulation_service: StoringSimulationService
) -> TestClient:
    """Serve the routes as the runtime role, creating through ``simulation_service``."""
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
        v2_stored_simulation_service_factory=lambda: V2StoredSimulationService(
            StoredSimulationDatabaseSession(sessions),
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


def report_body(policy_id: UUID) -> dict[str, Any]:
    return {
        "country_id": "us",
        "kind": "economy",
        "label": "Expanded child tax credit",
        "year": 2026,
        "region_code": "state/ca",
        "baseline": {},
        "reform": {"policy_id": str(policy_id)},
        "include_cliffs": True,
    }


def test_a_created_report_is_answered_as_the_tables_hold_it(
    owner_engine: Engine, catalog: CatalogRows, runtime_sessions: Any
) -> None:
    simulation_service = StoringSimulationService(owner_engine, catalog)

    response = client_for(runtime_sessions, simulation_service).post(
        "/v2/reports?country_id=us", json=report_body(catalog.policy_id)
    )

    assert response.status_code == 201, response.text
    item = response.json()["result"]["item"]
    assert item["id"] == str(catalog.report_ids[0])
    assert item["status"] == "pending"
    assert item["run"]["trigger"] == "initial"
    assert item["run"]["policyengine_version"] == "4.2.0"
    assert item["result"] is None
    assert item["current_versions"] == CURRENT_VERSIONS
    (sent,) = simulation_service.reports
    assert sent.reform.policy_id == catalog.policy_id
    assert sent.include_cliffs is True


def test_a_report_naming_a_policy_the_country_does_not_store_is_not_sent(
    owner_engine: Engine, catalog: CatalogRows, runtime_sessions: Any
) -> None:
    simulation_service = StoringSimulationService(owner_engine, catalog)

    response = client_for(runtime_sessions, simulation_service).post(
        "/v2/reports?country_id=us", json=report_body(uuid4())
    )

    assert response.status_code == 404
    assert simulation_service.reports == []


def test_a_created_report_that_cannot_be_read_back_answers_its_id(
    owner_engine: Engine, catalog: CatalogRows, runtime_sessions: Any
) -> None:
    # The simulation service answered that it created the report, so the
    # record exists: the caller gets its ID and is not invited to submit again.
    simulation_service = StoringSimulationService(
        owner_engine, catalog, answer_unstored=True
    )

    response = client_for(runtime_sessions, simulation_service).post(
        "/v2/reports?country_id=us", json=report_body(catalog.policy_id)
    )

    assert response.status_code == 502
    (report_id,) = simulation_service.unstored_ids
    # The run the answer named, which the stand-in made up with the report.
    run_id = response.json()["run_id"]
    assert response.json() == {
        "status": "error",
        "message": (
            f"The simulation service created report {report_id}, but it could "
            f"not be read back. Read it with GET /v2/reports/{report_id}"
            f"?country_id=us&run_id={run_id} rather than submitting it again."
        ),
        "report_id": str(report_id),
        "run_id": run_id,
    }


def test_a_created_simulation_that_cannot_be_read_back_answers_its_id(
    owner_engine: Engine, catalog: CatalogRows, runtime_sessions: Any
) -> None:
    simulation_service = StoringSimulationService(
        owner_engine, catalog, answer_unstored=True
    )

    response = client_for(runtime_sessions, simulation_service).post(
        "/v2/simulations?country_id=us",
        json={
            "country_id": "us",
            "kind": "economy",
            "year": 2026,
            "region_code": "state/ca",
        },
    )

    assert response.status_code == 502
    (simulation_id,) = simulation_service.unstored_ids
    assert response.json() == {
        "status": "error",
        "message": (
            f"The simulation service created simulation {simulation_id}, but it "
            f"could not be read back. Read it with GET /v2/simulations/"
            f"{simulation_id}?country_id=us rather than submitting it again."
        ),
        "simulation_id": str(simulation_id),
    }


def test_a_created_simulation_is_answered_as_the_tables_hold_it(
    owner_engine: Engine, catalog: CatalogRows, runtime_sessions: Any
) -> None:
    simulation_service = StoringSimulationService(owner_engine, catalog)

    response = client_for(runtime_sessions, simulation_service).post(
        "/v2/simulations?country_id=us",
        json={
            "country_id": "us",
            "kind": "economy",
            "year": 2026,
            "region_code": "state/ca",
            "policy_id": str(catalog.policy_id),
        },
    )

    assert response.status_code == 201, response.text
    item = response.json()["result"]["item"]
    assert item["id"] == str(catalog.simulation_ids[0])
    assert item["policy_id"] == str(catalog.policy_id)
    assert item["status"] == "pending"
    assert item["run"]["country_package_version"] == "1.5.0"
