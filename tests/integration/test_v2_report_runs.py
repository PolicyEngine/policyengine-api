"""Run v2 reports again and list their runs, on migrated PostgreSQL.

A stand-in for the simulation service's client stores the new run the
simulation service would create and records what it was asked; the routes
run as the Public API's runtime role, reading the report, checking its
country and policies, and reading the report and its runs back.
"""

from __future__ import annotations

from contextlib import contextmanager
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
    SimulationServiceConflictError,
    SimulationServiceUnavailableError,
)
from policyengine_api.services.v2.stored_reports.database_session import (
    StoredReportDatabaseSession,
)
from policyengine_api.services.v2.stored_reports.services import V2StoredReportService
from tests.integration.simulation_rows import insert_row
from tests.integration.stored_report_rows import (
    STARTED_AT,
    RunSettings,
    StoredReport,
    delete_catalog,
    store_catalog,
    store_report,
    store_report_run,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy import Connection, Engine

    from tests.integration.stored_report_rows import CatalogRows

CURRENT_VERSIONS = {"country_package_version": "1.5.0", "policyengine_version": "4.2.0"}
OLDER_VERSIONS = {"country_package_version": "1.4.0", "policyengine_version": "4.1.0"}


def current_versions(country_id: str) -> PackageVersions:
    return PackageVersions(**CURRENT_VERSIONS)


def mark_manual(connection: Connection, run_id: UUID) -> None:
    """Record the report run as a re-run, as the simulation service creates one."""
    connection.execute(
        text("UPDATE report_runs SET trigger = 'manual' WHERE id = :id"),
        {"id": run_id},
    )


@dataclass
class RerunningSimulationService:
    """Store the new run the simulation service would start, and record the ask.

    With ``delete_report``, the report is deleted once its new run is stored,
    so reading it back finds nothing. With ``refusal``, it stores nothing and
    raises it, as the simulation service refuses. With ``database_session``,
    it records how many of the report service's sessions are open when asked.
    """

    engine: Engine
    catalog: CatalogRows
    delete_report: bool = False
    refusal: Exception | None = None
    database_session: CountingDatabaseSession | None = None
    reruns: list[ReportRerunInput] = field(default_factory=list)
    new_run_ids: list[UUID] = field(default_factory=list)
    open_sessions_when_asked: list[int] = field(default_factory=list)

    def rerun_report(self, rerun: ReportRerunInput) -> None:
        self.reruns.append(rerun)
        if self.database_session is not None:
            self.open_sessions_when_asked.append(self.database_session.open_sessions)
        if self.refusal is not None:
            raise self.refusal
        with self.engine.begin() as connection:
            simulations = connection.execute(
                text(
                    "SELECT baseline_simulation_id, reform_simulation_id FROM "
                    "reports WHERE id = :id"
                ),
                {"id": rerun.report_id},
            ).one()
            report = StoredReport(
                report_id=rerun.report_id,
                baseline_simulation_id=simulations.baseline_simulation_id,
                reform_simulation_id=simulations.reform_simulation_id,
            )
            run_ids = store_report_run(
                connection,
                self.catalog,
                report,
                RunSettings(
                    versions=CURRENT_VERSIONS,
                    status="pending",
                    created_at=STARTED_AT + timedelta(days=30),
                ),
            )
            mark_manual(connection, run_ids.report_run_id)
            self.new_run_ids.append(run_ids.report_run_id)
            if self.delete_report:
                connection.execute(
                    text("DELETE FROM reports WHERE id = :id"),
                    {"id": rerun.report_id},
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


class CountingDatabaseSession(StoredReportDatabaseSession):
    """Count the report service's read sessions open at each moment."""

    def __init__(self, sessions: Any) -> None:
        super().__init__(sessions)
        self.open_sessions = 0

    @contextmanager
    def read(self) -> Iterator[Session]:
        self.open_sessions += 1
        try:
            with super().read() as session:
                yield session
        finally:
            self.open_sessions -= 1


def client_for(
    sessions: Any,
    simulation_service: RerunningSimulationService,
    database_session: StoredReportDatabaseSession | None = None,
) -> TestClient:
    """Serve the routes as the runtime role, running reports through the stand-in."""
    submissions = SimulationSubmissionService(
        countries=V2CountryService(CountryDatabaseSession(sessions)),
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
            database_session or StoredReportDatabaseSession(sessions),
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


def test_a_reports_runs_are_listed_newest_first_with_their_versions(
    owner_engine: Engine, catalog: CatalogRows, runtime_sessions: Any
) -> None:
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
        first = store_report_run(
            connection,
            catalog,
            report,
            RunSettings(versions=OLDER_VERSIONS, status="succeeded"),
        )
        failed = store_report_run(
            connection,
            catalog,
            report,
            RunSettings(
                versions=CURRENT_VERSIONS,
                status="failed",
                created_at=STARTED_AT + timedelta(days=1),
                error_message="The reform simulation failed",
            ),
        )
        mark_manual(connection, failed.report_run_id)
        newest = store_report_run(
            connection,
            catalog,
            report,
            RunSettings(
                versions=CURRENT_VERSIONS,
                status="running",
                created_at=STARTED_AT + timedelta(days=2),
            ),
        )
        mark_manual(connection, newest.report_run_id)
        other_report = store_report(connection, catalog)
        store_report_run(
            connection,
            catalog,
            other_report,
            RunSettings(versions=CURRENT_VERSIONS),
        )
    client = client_for(
        runtime_sessions, RerunningSimulationService(owner_engine, catalog)
    )

    response = client.get(f"/v2/reports/{report.report_id}/runs?country_id=us")

    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["report_id"] == str(report.report_id)
    assert result["kind"] == "economy"
    assert result["current_versions"] == CURRENT_VERSIONS
    items = result["items"]
    assert [item["id"] for item in items] == [
        str(newest.report_run_id),
        str(failed.report_run_id),
        str(first.report_run_id),
    ]
    assert [(item["status"], item["trigger"]) for item in items] == [
        ("running", "manual"),
        ("failed", "manual"),
        ("succeeded", "initial"),
    ]
    assert [item["policyengine_version"] for item in items] == [
        "4.2.0",
        "4.2.0",
        "4.1.0",
    ]
    assert items[1]["error_message"] == "The reform simulation failed"
    assert items[2]["baseline_simulation_run_id"] == str(
        first.baseline_simulation_run_id
    )
    assert items[2]["reform_simulation_run_id"] == str(first.reform_simulation_run_id)


def test_a_report_with_no_run_lists_none(
    owner_engine: Engine, catalog: CatalogRows, runtime_sessions: Any
) -> None:
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
    client = client_for(
        runtime_sessions, RerunningSimulationService(owner_engine, catalog)
    )

    response = client.get(f"/v2/reports/{report.report_id}/runs?country_id=us")

    assert response.status_code == 200, response.text
    assert response.json()["result"]["items"] == []


@pytest.mark.parametrize("method", ["get", "post"])
def test_another_countrys_report_or_an_unknown_one_is_not_found(
    owner_engine: Engine, catalog: CatalogRows, runtime_sessions: Any, method: str
) -> None:
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
    simulation_service = RerunningSimulationService(owner_engine, catalog)
    client = client_for(runtime_sessions, simulation_service)

    other_country = client.request(
        method, f"/v2/reports/{report.report_id}/runs?country_id=uk", json={}
    )
    unknown = client.request(
        method, f"/v2/reports/{uuid4()}/runs?country_id=us", json={}
    )

    assert other_country.status_code == 404
    assert unknown.status_code == 404
    assert simulation_service.reruns == []


def store_household_report(connection: Connection, catalog: CatalogRows) -> UUID:
    """Store a household and a report over it; return the report's ID."""
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
    return store_report(connection, catalog, household_id=household_id).report_id


def store_budget_window(connection: Connection, catalog: CatalogRows) -> UUID:
    """Store a three-year budget window; return its report's ID."""
    return store_report(connection, catalog, budget_window_size=3).report_id


@dataclass(frozen=True)
class OtherKind:
    """A kind of report the run routes refuse: its name and how to store one."""

    name: str
    store: Callable[[Connection, CatalogRows], UUID]


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize(
    "other_kind",
    [
        OtherKind("a budget window", store_budget_window),
        OtherKind("a household report", store_household_report),
    ],
    ids=["budget-window", "household"],
)
def test_other_kinds_runs_are_not_listed_or_started_here_yet(
    owner_engine: Engine,
    catalog: CatalogRows,
    runtime_sessions: Any,
    method: str,
    other_kind: OtherKind,
) -> None:
    with owner_engine.begin() as connection:
        report_id = other_kind.store(connection, catalog)
    simulation_service = RerunningSimulationService(owner_engine, catalog)
    client = client_for(runtime_sessions, simulation_service)

    response = client.request(
        method, f"/v2/reports/{report_id}/runs?country_id=us", json={}
    )

    assert response.status_code == 422
    assert response.json()["message"] == (
        f"Report {report_id} is {other_kind.name}, whose runs these routes do not "
        "start or list yet"
    )
    assert simulation_service.reruns == []


@pytest.mark.parametrize("force", [False, True])
def test_running_a_report_again_answers_it_with_its_new_run(
    owner_engine: Engine,
    catalog: CatalogRows,
    runtime_sessions: Any,
    force: bool,  # noqa: FBT001  # pytest passes parameters positionally
) -> None:
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
        first = store_report_run(
            connection, catalog, report, RunSettings(versions=OLDER_VERSIONS)
        )
    simulation_service = RerunningSimulationService(owner_engine, catalog)
    client = client_for(runtime_sessions, simulation_service)

    response = client.post(
        f"/v2/reports/{report.report_id}/runs?country_id=us", json={"force": force}
    )

    assert response.status_code == 201, response.text
    assert simulation_service.reruns == [
        ReportRerunInput(
            country_id="us",
            report_id=report.report_id,
            force=force,
            policy_ids=(None, catalog.policy_id),
        )
    ]
    item = response.json()["result"]["item"]
    (new_run_id,) = simulation_service.new_run_ids
    assert item["id"] == str(report.report_id)
    assert item["status"] == "pending"
    assert item["run"]["id"] == str(new_run_id)
    assert item["run"]["trigger"] == "manual"
    assert item["run"]["policyengine_version"] == "4.2.0"
    assert item["current_versions"] == CURRENT_VERSIONS
    assert item["result"] is None
    runs = client.get(f"/v2/reports/{report.report_id}/runs?country_id=us").json()
    assert [run["id"] for run in runs["result"]["items"]] == [
        str(new_run_id),
        str(first.report_run_id),
    ]


def test_a_report_whose_reform_simulation_is_gone_is_left_to_the_service_to_refuse(
    owner_engine: Engine, catalog: CatalogRows, runtime_sessions: Any
) -> None:
    # The Public API checks the policies that remain and asks the simulation
    # service, which refuses a report missing a simulation.
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
        connection.execute(
            text("UPDATE reports SET reform_simulation_id = NULL WHERE id = :id"),
            {"id": report.report_id},
        )
    message = (
        "The simulation service will not run the report again now "
        "(rerun_not_supported): The report has no reform simulation."
    )
    simulation_service = RerunningSimulationService(
        owner_engine, catalog, refusal=SimulationServiceConflictError(message)
    )
    client = client_for(runtime_sessions, simulation_service)

    response = client.post(
        f"/v2/reports/{report.report_id}/runs?country_id=us", json={}
    )

    assert response.status_code == 409
    assert response.json() == {"status": "error", "message": message, "run_id": None}
    assert [rerun.policy_ids for rerun in simulation_service.reruns] == [(None, None)]


def test_a_new_run_whose_report_cannot_be_read_back_answers_the_reports_id(
    owner_engine: Engine, catalog: CatalogRows, runtime_sessions: Any
) -> None:
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
    simulation_service = RerunningSimulationService(
        owner_engine, catalog, delete_report=True
    )

    response = client_for(runtime_sessions, simulation_service).post(
        f"/v2/reports/{report.report_id}/runs?country_id=us", json={}
    )

    assert response.status_code == 502
    assert response.json() == {
        "status": "error",
        "message": (
            f"The simulation service started a new run of report "
            f"{report.report_id}, but the report could not be read back. Read it "
            f"with GET /v2/reports/{report.report_id}?country_id=us rather than "
            "running it again."
        ),
        "report_id": str(report.report_id),
    }


def test_no_report_session_is_open_while_the_simulation_service_is_asked(
    owner_engine: Engine, catalog: CatalogRows, runtime_sessions: Any
) -> None:
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
    database_session = CountingDatabaseSession(runtime_sessions)
    simulation_service = RerunningSimulationService(
        owner_engine, catalog, database_session=database_session
    )
    client = client_for(runtime_sessions, simulation_service, database_session)

    response = client.post(
        f"/v2/reports/{report.report_id}/runs?country_id=us", json={}
    )

    assert response.status_code == 201, response.text
    assert simulation_service.open_sessions_when_asked == [0]
    assert database_session.open_sessions == 0


def test_the_simulation_services_refusal_is_answered_as_its_own(
    owner_engine: Engine, catalog: CatalogRows, runtime_sessions: Any
) -> None:
    # The report exists, so the service's refusal is not mistaken for a
    # report that cannot be read back.
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
    message = "The simulation service is unavailable (503 manifest_unavailable)."
    simulation_service = RerunningSimulationService(
        owner_engine, catalog, refusal=SimulationServiceUnavailableError(message)
    )

    response = client_for(runtime_sessions, simulation_service).post(
        f"/v2/reports/{report.report_id}/runs?country_id=us", json={}
    )

    assert response.status_code == 503
    assert response.json() == {"status": "error", "message": message}
