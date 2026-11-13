"""Stand-ins and row helpers for the tests of users' report-run records.

``JoiningSimulationService`` answers creates and re-runs as the simulation
service does once identical requests share runs: with a run it names, or
with a new pending run it stores. The helpers serve the report routes as the
Public API's runtime role and read users' records and saved reports back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from flask import Flask
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.libs.user_auth import UNAUTHENTICATED_USER_HEADER
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
from policyengine_api.services.v2.report_run_records.database_session import (
    ReportRunRecordDatabaseSession,
)
from policyengine_api.services.v2.report_run_records.services import (
    ReportRunRecordService,
)
from policyengine_api.services.v2.simulation_service.services import (
    SimulationSubmissionService,
)
from policyengine_api.services.v2.simulation_service.types import (
    PackageVersions,
    ReportRerunInput,
    StartedReportRun,
    SubmittedBudgetWindow,
    SubmittedReport,
)
from policyengine_api.services.v2.stored_reports.database_session import (
    StoredReportDatabaseSession,
)
from policyengine_api.services.v2.stored_reports.services import V2StoredReportService
from tests.fixtures.economy_results import us_economy_result
from tests.integration.stored_report_rows import (
    STARTED_AT,
    BudgetWindowYear,
    RunSettings,
    StoredReport,
    store_budget_window_run,
    store_report,
    store_report_run,
    store_year_simulations,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    from sqlalchemy import Connection, Engine
    from sqlmodel import Session

    from policyengine_api.services.v2.identity.types import AccountPrincipal
    from policyengine_api.services.v2.simulation_service.types import (
        BudgetWindowReportCreationInput,
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
    run of the report, as before, marked forced for a forced re-run. With
    ``during_call``, each create and re-run first runs it, as something
    another request does while the simulation service is asked.
    """

    engine: Engine
    catalog: CatalogRows
    joined_run: JoinedRun | None = None
    during_call: Callable[[], None] | None = None
    reports: list[EconomyReportCreationInput] = field(default_factory=list)
    reruns: list[ReportRerunInput] = field(default_factory=list)

    def submit_report(self, report: EconomyReportCreationInput) -> SubmittedReport:
        self.reports.append(report)
        if self.during_call is not None:
            self.during_call()
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

    def submit_budget_window(
        self, report: BudgetWindowReportCreationInput
    ) -> SubmittedBudgetWindow:
        if self.during_call is not None:
            self.during_call()
        if self.joined_run is not None:
            if self.joined_run.budget_window_run_id is None:
                msg = "a budget window joins a budget-window run"
                raise AssertionError(msg)
            return SubmittedBudgetWindow(
                report_id=self.joined_run.report_id,
                budget_window_run_id=self.joined_run.budget_window_run_id,
            )
        with self.engine.begin() as connection:
            window = store_window(
                connection,
                self.catalog,
                years=tuple(
                    range(report.year, report.year + report.budget_window_size)
                ),
                settings=RunSettings(versions=CURRENT_VERSIONS, status="pending"),
            )
        return SubmittedBudgetWindow(
            report_id=window.report.report_id,
            budget_window_run_id=window.window_run_id,
        )

    def rerun_report(self, rerun: ReportRerunInput) -> StartedReportRun:
        self.reruns.append(rerun)
        if self.during_call is not None:
            self.during_call()
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
                    forced=rerun.force,
                ),
            )
        return StartedReportRun(report_run_id=run_ids.report_run_id)


class UnwritableRecordSession(ReportRunRecordDatabaseSession):
    """Read as usual, but fail every transaction, as an unavailable database does."""

    def transaction(self) -> AbstractContextManager[Session]:
        statement = "INSERT INTO user_report_run_associations"
        raise OperationalError(statement, {}, Exception("connection refused"))


def client_for(
    sessions: Any,
    simulation_service: JoiningSimulationService,
    *,
    record_session: ReportRunRecordDatabaseSession | None = None,
    requester: AccountPrincipal | None = None,
) -> TestClient:
    """Serve the report routes as the runtime role, through the stand-in.

    Users' report runs are recorded through ``record_session``, by default
    the runtime role's. With ``requester``, every request acts for that
    principal, as a signed-in user's verified bearer token does; without it,
    the request's own credential decides.
    """
    submissions = SimulationSubmissionService(
        countries=V2CountryService(CountryDatabaseSession(sessions)),
        households=V2HouseholdService(HouseholdDatabaseSession(sessions)),
        policies=V2PolicyService(
            PolicyDatabaseSession(sessions), running_policyengine_version="4.2.0"
        ),
        client_factory=lambda: simulation_service,
    )
    signed_in = {} if requester is None else {"optional_user": lambda: requester}
    dependencies = NativeRouteDependencies(
        **signed_in,
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        v2_stored_report_service_factory=lambda: V2StoredReportService(
            StoredReportDatabaseSession(sessions),
            current_versions=current_versions,
            submissions=submissions,
            run_records=ReportRunRecordService(
                record_session or ReportRunRecordDatabaseSession(sessions)
            ),
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

    A succeeded run to join has its result stored. Return the report, the
    run to join and the forced run, which is the report's newest.
    """
    report = store_report(connection, catalog)
    joined = store_report_run(
        connection,
        catalog,
        report,
        RunSettings(versions=CURRENT_VERSIONS, status=joined_status),
        result=us_economy_result() if joined_status == "succeeded" else None,
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


@dataclass(frozen=True)
class RunRecord:
    """A user's stored request for a report run."""

    user_id: UUID
    report_run_id: UUID
    trigger: str
    requested_at: datetime


def as_browser(browser_id: UUID) -> dict[str, str]:
    return {UNAUTHENTICATED_USER_HEADER: str(browser_id)}


def stored_records(engine: Engine, user_ids: list[UUID]) -> list[RunRecord]:
    with engine.begin() as connection:
        rows = connection.execute(
            text(
                "SELECT user_id, report_run_id, trigger, requested_at FROM "
                "user_report_run_associations WHERE user_id = ANY(:ids) "
                "ORDER BY requested_at, user_id"
            ),
            {"ids": user_ids},
        ).all()
    return [
        RunRecord(
            user_id=row.user_id,
            report_run_id=row.report_run_id,
            trigger=row.trigger,
            requested_at=row.requested_at,
        )
        for row in rows
    ]


def store_saved_report(engine: Engine, *, user_id: UUID, report_id: UUID) -> UUID:
    """Save the report for the user, with no last run time, and return its ID."""
    saved_report_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, user_type) VALUES (:id, 'unauthenticated') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": user_id},
        )
        connection.execute(
            text(
                "INSERT INTO user_report_associations (id, user_id, report_id, "
                "country_id, name) VALUES (:id, :user_id, :report_id, 'us', "
                "'My report')"
            ),
            {"id": saved_report_id, "user_id": user_id, "report_id": report_id},
        )
    return saved_report_id


def saved_report_last_run_at(engine: Engine, saved_report_id: UUID) -> datetime | None:
    with engine.begin() as connection:
        return connection.execute(
            text("SELECT last_run_at FROM user_report_associations WHERE id = :id"),
            {"id": saved_report_id},
        ).scalar_one()


def rerun_as_browser(client: TestClient, report_id: UUID, browser_id: UUID) -> None:
    """Run the report again, forced so each re-run is a new run, as the browser."""
    response = client.post(
        f"/v2/reports/{report_id}/runs?country_id=us",
        json={"force": True},
        headers=as_browser(browser_id),
    )
    assert response.status_code == 201, response.text


def newest_request(engine: Engine, user_id: UUID) -> datetime:
    return max(record.requested_at for record in stored_records(engine, [user_id]))


@dataclass(frozen=True)
class StoredWindow:
    """A budget-window report, one of its window runs and that run's year runs."""

    report: StoredReport
    window_run_id: UUID
    year_run_ids: tuple[UUID, ...]


def store_window(
    connection: Connection,
    catalog: CatalogRows,
    *,
    years: tuple[int, ...],
    settings: RunSettings,
    report: StoredReport | None = None,
) -> StoredWindow:
    """Store a window run of ``report`` (a new window if None) with a run per year."""
    window = (
        store_report(connection, catalog, budget_window_size=len(years), year=years[0])
        if report is None
        else report
    )
    window_run_id = store_budget_window_run(connection, catalog, window, settings)
    year_run_ids = tuple(
        store_report_run(
            connection,
            catalog,
            store_year_simulations(connection, catalog, window, year),
            RunSettings(
                versions=settings.versions,
                status=settings.status,
                created_at=settings.created_at,
                budget_window_year=BudgetWindowYear(
                    budget_window_run_id=window_run_id, year=year
                ),
            ),
        ).report_run_id
        for year in years
    )
    return StoredWindow(
        report=window, window_run_id=window_run_id, year_run_ids=year_run_ids
    )


def window_body(policy_id: UUID, *, years: int) -> dict[str, Any]:
    return {
        "country_id": "us",
        "kind": "budget_window",
        "label": "Expanded child tax credit, over years",
        "year": 2026,
        "budget_window_size": years,
        "region_code": "state/ca",
        "baseline": {},
        "reform": {"policy_id": str(policy_id)},
    }
