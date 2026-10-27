"""A fake Simulation Entrypoint and economy report records for unit tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine

from policyengine_api.data.v2.models import V2_METADATA, Country
from policyengine_api.services.v2.economy_reports.database_session import (
    EconomyReportDatabaseSession,
)
from policyengine_api.services.v2.economy_reports.services import (
    V2EconomyReportService,
)
from policyengine_api.services.v2.economy_reports.types import (
    ComparisonRecord,
    EconomyReportRecord,
    EconomyReportRunRecord,
    ReportStatus,
    SimulationRecord,
    SimulationRecordNotFoundError,
    SimulationRunRecord,
)
from tests.fixtures.v2_countries import add_listed_countries

if TYPE_CHECKING:
    from policyengine_api.services.v2.economy_reports.types import (
        EconomyReportSubmission,
        RunTrigger,
    )

CURRENT_POLICYENGINE_VERSION = "6.7.5"
REPORT_ID = UUID("00000000-0000-4000-8000-000000000101")
BASELINE_SIMULATION_ID = UUID("00000000-0000-4000-8000-000000000102")
REFORM_SIMULATION_ID = UUID("00000000-0000-4000-8000-000000000103")
REPORT_RUN_ID = UUID("00000000-0000-4000-8000-000000000104")
BASELINE_RUN_ID = UUID("00000000-0000-4000-8000-000000000105")
REFORM_RUN_ID = UUID("00000000-0000-4000-8000-000000000106")
CATALOG_VERSION_ID = UUID("00000000-0000-4000-8000-000000000107")
REFORM_POLICY_ID = UUID("00000000-0000-4000-8000-000000000108")
CREATED_AT = datetime(2026, 10, 27, 12, tzinfo=UTC)
# A country that has only household calculations; no real country does yet.
HOUSEHOLD_ONLY_COUNTRY = Country(
    id="zz", household_enabled=True, society_wide_enabled=False
)
RESULT = {"budget": {"budgetary_impact": -1250000.0}}


def simulation_record(
    simulation_id: UUID,
    *,
    policy_id: UUID | None = None,
    country_id: str = "us",
) -> SimulationRecord:
    return SimulationRecord(
        id=simulation_id,
        kind="economy",
        country_id=country_id,
        policy_id=policy_id,
        dynamic_id=None,
        region_code="state/ca",
        dataset_name=None,
        legacy_simulation_id=None,
        created_at=CREATED_AT,
    )


def _simulation_run(run_id: UUID, simulation_id: UUID) -> SimulationRunRecord:
    return SimulationRunRecord(
        id=run_id,
        simulation_id=simulation_id,
        status="pending",
        attempt=1,
        trigger="initial",
        error=None,
        dispatched_at=None,
        completed_at=None,
        created_at=CREATED_AT,
    )


def report_run_record(
    *,
    run_id: UUID = REPORT_RUN_ID,
    trigger: str = "initial",
    status: ReportStatus = ReportStatus.PENDING,
    policyengine_version: str = CURRENT_POLICYENGINE_VERSION,
) -> EconomyReportRunRecord:
    return EconomyReportRunRecord(
        id=run_id,
        report_id=REPORT_ID,
        trigger=trigger,
        tax_benefit_model_version_id=CATALOG_VERSION_ID,
        policyengine_version=policyengine_version,
        year=2026,
        status=status,
        stage="queued" if status is ReportStatus.PENDING else None,
        error=None,
        baseline_run=_simulation_run(BASELINE_RUN_ID, BASELINE_SIMULATION_ID),
        reform_run=_simulation_run(REFORM_RUN_ID, REFORM_SIMULATION_ID),
        comparison=ComparisonRecord(
            status="pending", error=None, dispatched_at=None, completed_at=None
        ),
        created_at=CREATED_AT,
    )


def report_record(
    *,
    report_id: UUID = REPORT_ID,
    country_id: str = "us",
    run: EconomyReportRunRecord | None = None,
    legacy_report_id: int | None = None,
) -> EconomyReportRecord:
    """Build a report: not run without a run, with a result once it succeeded."""
    status = ReportStatus.NOT_RUN if run is None else run.status
    return EconomyReportRecord(
        id=report_id,
        country_id=country_id,
        year=2026,
        options={},
        legacy_report_id=legacy_report_id,
        created_at=CREATED_AT,
        baseline_simulation=simulation_record(
            BASELINE_SIMULATION_ID, country_id=country_id
        ),
        reform_simulation=simulation_record(
            REFORM_SIMULATION_ID, policy_id=REFORM_POLICY_ID, country_id=country_id
        ),
        status=status,
        run=run,
        result=RESULT if status is ReportStatus.SUCCEEDED else None,
    )


class FakeEconomyReportSimulation:
    """An in-memory Simulation Entrypoint that records every call.

    ``reports`` and ``simulations`` hold what it knows; ``error`` is raised by
    every call while set, and ``run_error`` by run starts only.
    """

    def __init__(self, *reports: EconomyReportRecord) -> None:
        self.reports = {report.id: report for report in reports}
        self.simulations: dict[UUID, SimulationRecord] = {}
        self.runs: dict[UUID, list[EconomyReportRunRecord]] = {}
        self.calls: list[tuple[str, object]] = []
        self.error: Exception | None = None
        self.run_error: Exception | None = None
        self.next_run = report_run_record()

    def _record(self, name: str, argument: object) -> None:
        self.calls.append((name, argument))
        if self.error is not None:
            raise self.error

    def submit_report(self, submission: EconomyReportSubmission) -> EconomyReportRecord:
        self._record("submit_report", submission)
        report = report_record(country_id=submission.country_id, run=self.next_run)
        self.reports[report.id] = report
        return report

    def get_report(self, report_id: UUID) -> EconomyReportRecord:
        self._record("get_report", report_id)
        if report_id not in self.reports:
            msg = f"no economy report {report_id}"
            raise SimulationRecordNotFoundError(msg)
        return self.reports[report_id]

    def get_report_by_legacy_id(self, legacy_report_id: int) -> EconomyReportRecord:
        self._record("get_report_by_legacy_id", legacy_report_id)
        for report in self.reports.values():
            if report.legacy_report_id == legacy_report_id:
                return report
        msg = f"no economy report {legacy_report_id}"
        raise SimulationRecordNotFoundError(msg)

    def run_report(
        self,
        report_id: UUID,
        *,
        policyengine_version: str,
        trigger: RunTrigger,
        force: bool,
    ) -> EconomyReportRunRecord:
        self._record(
            "run_report",
            {
                "report_id": report_id,
                "policyengine_version": policyengine_version,
                "trigger": trigger,
                "force": force,
            },
        )
        if self.run_error is not None:
            raise self.run_error
        if report_id not in self.reports:
            msg = f"no report {report_id}"
            raise SimulationRecordNotFoundError(msg)
        run = replace(self.next_run, trigger=trigger.value)
        self.runs.setdefault(report_id, []).insert(0, run)
        self.reports[report_id] = replace(
            self.reports[report_id], run=run, status=run.status, result=None
        )
        return run

    def list_report_runs(self, report_id: UUID) -> tuple[EconomyReportRunRecord, ...]:
        self._record("list_report_runs", report_id)
        if report_id not in self.reports:
            msg = f"no economy report {report_id}"
            raise SimulationRecordNotFoundError(msg)
        return tuple(self.runs.get(report_id, ()))

    def get_simulation(self, simulation_id: UUID) -> SimulationRecord:
        self._record("get_simulation", simulation_id)
        if simulation_id not in self.simulations:
            msg = f"no simulation {simulation_id}"
            raise SimulationRecordNotFoundError(msg)
        return self.simulations[simulation_id]


def countries_store(*extra_countries: Country) -> sessionmaker[Session]:
    """Build an SQLite v2 schema with the US and UK rows and ``extra_countries``.

    Routes run in a worker thread, so every session shares one connection to
    the in-memory database.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    V2_METADATA.create_all(engine)
    sessions = sessionmaker(engine, class_=Session)
    with sessions() as session:
        add_listed_countries(session)
        session.add_all(extra_countries)
        session.commit()
    return sessions


def economy_report_service(
    simulation: FakeEconomyReportSimulation,
    sessions: sessionmaker[Session] | None = None,
) -> V2EconomyReportService:
    return V2EconomyReportService(
        EconomyReportDatabaseSession(
            countries_store(HOUSEHOLD_ONLY_COUNTRY) if sessions is None else sessions
        ),
        simulation,
        current_policyengine_version=CURRENT_POLICYENGINE_VERSION,
    )
