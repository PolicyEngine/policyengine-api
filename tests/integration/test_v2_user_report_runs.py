"""Create and re-run v2 reports whose runs other requests share, on PostgreSQL.

Once the simulation service finds or creates reports and runs by key, a
request may end on a run that already exists: it answers 201 naming that
run, and a re-run while a run is pending or running answers that run rather
than 409. A stand-in for the simulation service's client answers so: with a
run it names (``joined_run``), or else with a new pending run it stores. The
routes run as the Public API's runtime role and read the report back with
the run the answer names, whichever run is the report's newest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    ReportRerunInput,
    StartedReportRun,
    SubmittedReport,
)
from policyengine_api.services.v2.stored_reports.database_session import (
    StoredReportDatabaseSession,
)
from policyengine_api.services.v2.stored_reports.services import V2StoredReportService
from tests.integration.stored_report_rows import (
    STARTED_AT,
    BudgetWindowYear,
    RunSettings,
    StoredReport,
    delete_catalog,
    store_budget_window_run,
    store_catalog,
    store_report,
    store_report_run,
    store_year_simulations,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from uuid import UUID

    from sqlalchemy import Engine

    from policyengine_api.services.v2.simulation_service.types import (
        EconomyReportCreationInput,
    )
    from tests.integration.stored_report_rows import CatalogRows

CURRENT_VERSIONS = {"country_package_version": "1.5.0", "policyengine_version": "4.2.0"}
WINDOW_YEARS = (2026, 2027)


def current_versions(country_id: str) -> PackageVersions:
    return PackageVersions(**CURRENT_VERSIONS)


@dataclass(frozen=True)
class JoinedRun:
    """A run an answer names that the request didn't create.

    ``budget_window_run_id`` is set for a budget window's run, whose first
    year's report run is ``report_run_id``.
    """

    report_id: UUID
    report_run_id: UUID
    budget_window_run_id: UUID | None = None


@dataclass
class JoiningSimulationService:
    """Answer as the simulation service does once identical requests share runs.

    With ``joined_run``, every create and re-run answers that run and stores
    nothing, as a request that finds an existing run does. Without it, a
    create stores a new report with a pending run, and a re-run a new pending
    run of the report, as before.
    """

    engine: Engine
    catalog: CatalogRows
    joined_run: JoinedRun | None = None
    reports: list[EconomyReportCreationInput] = field(default_factory=list)
    reruns: list[ReportRerunInput] = field(default_factory=list)

    def submit_report(self, report: EconomyReportCreationInput) -> SubmittedReport:
        self.reports.append(report)
        if self.joined_run is not None:
            return SubmittedReport(
                report_id=self.joined_run.report_id,
                report_run_id=self.joined_run.report_run_id,
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

    def rerun_report(self, rerun: ReportRerunInput) -> StartedReportRun:
        self.reruns.append(rerun)
        if self.joined_run is not None:
            return StartedReportRun(
                report_run_id=self.joined_run.report_run_id,
                budget_window_run_id=self.joined_run.budget_window_run_id,
            )
        with self.engine.begin() as connection:
            simulations = connection.execute(
                text(
                    "SELECT baseline_simulation_id, reform_simulation_id FROM "
                    "reports WHERE id = :id"
                ),
                {"id": rerun.report_id},
            ).one()
            run_ids = store_report_run(
                connection,
                self.catalog,
                StoredReport(
                    report_id=rerun.report_id,
                    baseline_simulation_id=simulations.baseline_simulation_id,
                    reform_simulation_id=simulations.reform_simulation_id,
                ),
                RunSettings(
                    versions=CURRENT_VERSIONS,
                    status="pending",
                    created_at=STARTED_AT + timedelta(days=30),
                ),
            )
        return StartedReportRun(report_run_id=run_ids.report_run_id)


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
    sessions: Any, simulation_service: JoiningSimulationService
) -> TestClient:
    """Serve the report routes as the runtime role, through the stand-in."""
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


def report_body(policy_id: UUID) -> dict[str, Any]:
    return {
        "country_id": "us",
        "kind": "economy",
        "label": "Expanded child tax credit",
        "year": 2026,
        "region_code": "state/ca",
        "baseline": {},
        "reform": {"policy_id": str(policy_id)},
    }


def store_joined_and_newer_forced_run(
    connection: Any, catalog: CatalogRows, *, joined_status: str
) -> tuple[StoredReport, UUID, UUID]:
    """Store a report with a run to join and a newer forced run beside it.

    Return the report, the run to join and the forced run, which is the
    report's newest.
    """
    report = store_report(connection, catalog)
    joined = store_report_run(
        connection,
        catalog,
        report,
        RunSettings(versions=CURRENT_VERSIONS, status=joined_status),
    )
    forced = store_report_run(
        connection,
        catalog,
        report,
        RunSettings(
            versions=CURRENT_VERSIONS,
            status="running",
            created_at=STARTED_AT + timedelta(days=1),
            forced=True,
        ),
    )
    return report, joined.report_run_id, forced.report_run_id


def test_a_create_that_joins_a_run_answers_that_run_not_the_reports_newest(
    owner_engine: Engine, catalog: CatalogRows, runtime_sessions: Any
) -> None:
    with owner_engine.begin() as connection:
        report, joined_run_id, _forced_run_id = store_joined_and_newer_forced_run(
            connection, catalog, joined_status="succeeded"
        )
    simulation_service = JoiningSimulationService(
        owner_engine,
        catalog,
        joined_run=JoinedRun(report_id=report.report_id, report_run_id=joined_run_id),
    )

    response = client_for(runtime_sessions, simulation_service).post(
        "/v2/reports?country_id=us", json=report_body(catalog.policy_id)
    )

    assert response.status_code == 201, response.text
    item = response.json()["result"]["item"]
    assert item["id"] == str(report.report_id)
    assert item["run"]["id"] == str(joined_run_id)
    assert item["status"] == "succeeded"


def test_a_rerun_while_a_run_is_under_way_answers_201_with_that_run(
    owner_engine: Engine, catalog: CatalogRows, runtime_sessions: Any
) -> None:
    with owner_engine.begin() as connection:
        report, joined_run_id, _forced_run_id = store_joined_and_newer_forced_run(
            connection, catalog, joined_status="pending"
        )
    simulation_service = JoiningSimulationService(
        owner_engine,
        catalog,
        joined_run=JoinedRun(report_id=report.report_id, report_run_id=joined_run_id),
    )

    response = client_for(runtime_sessions, simulation_service).post(
        f"/v2/reports/{report.report_id}/runs?country_id=us", json={}
    )

    assert response.status_code == 201, response.text
    item = response.json()["result"]["item"]
    assert item["run"]["id"] == str(joined_run_id)
    assert item["status"] == "pending"


def test_a_budget_window_rerun_answers_the_window_run_it_joined(
    owner_engine: Engine, catalog: CatalogRows, runtime_sessions: Any
) -> None:
    with owner_engine.begin() as connection:
        window = store_report(connection, catalog, budget_window_size=2)
        window_run_ids = []
        first_year_run_ids = []
        for days_later in (0, 1):
            settings = RunSettings(
                versions=CURRENT_VERSIONS,
                status="pending",
                created_at=STARTED_AT + timedelta(days=days_later),
                forced=days_later == 1,
            )
            window_run_id = store_budget_window_run(
                connection, catalog, window, settings
            )
            window_run_ids.append(window_run_id)
            for year in WINDOW_YEARS:
                year_run = store_report_run(
                    connection,
                    catalog,
                    store_year_simulations(connection, catalog, window, year),
                    RunSettings(
                        versions=CURRENT_VERSIONS,
                        status="pending",
                        created_at=settings.created_at,
                        budget_window_year=BudgetWindowYear(
                            budget_window_run_id=window_run_id, year=year
                        ),
                        forced=settings.forced,
                    ),
                )
                if year == WINDOW_YEARS[0]:
                    first_year_run_ids.append(year_run.report_run_id)
    joined = JoinedRun(
        report_id=window.report_id,
        report_run_id=first_year_run_ids[0],
        budget_window_run_id=window_run_ids[0],
    )
    simulation_service = JoiningSimulationService(
        owner_engine, catalog, joined_run=joined
    )

    response = client_for(runtime_sessions, simulation_service).post(
        f"/v2/reports/{window.report_id}/runs?country_id=us", json={}
    )

    assert response.status_code == 201, response.text
    item = response.json()["result"]["item"]
    assert item["kind"] == "budget_window"
    assert item["run"]["id"] == str(window_run_ids[0])
