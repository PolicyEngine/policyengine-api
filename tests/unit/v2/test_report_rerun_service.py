"""Run reports again and list their runs in the report service, without a database."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import OperationalError

from policyengine_api.data.v2.models import (
    BudgetWindowRun,
    Report,
    ReportRunStatus,
    ReportRunTrigger,
)
from policyengine_api.services.v2.simulation_service.types import (
    PackageVersions,
    StartedReportRun,
)
from policyengine_api.services.v2.stored_reports.services import (
    SubmissionsNotConfiguredError,
    V2StoredReportService,
)
from policyengine_api.services.v2.stored_reports.transformations import (
    budget_window_runs_read,
)
from policyengine_api.services.v2.stored_reports.types import StoredReportRows
from policyengine_api.services.v2.stored_reports.validators import ReportStorageError

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from sqlmodel import Session

    from policyengine_api.services.v2.simulation_service.types import (
        ReportRerunInput,
    )

REPORT_ID = UUID("00000000-0000-0000-0000-00000000f001")
STORED_AT = datetime(2026, 11, 13, 9, tzinfo=UTC)
CURRENT_VERSIONS = PackageVersions(
    country_package_version="1.5.0", policyengine_version="4.2.0"
)


@dataclass
class FailingDatabaseSession:
    """A database that cannot be read: opening a session fails."""

    error: Exception = field(
        default_factory=lambda: OperationalError(
            "SELECT 1", {}, Exception("connection refused")
        )
    )
    opened: int = 0

    def read(self) -> AbstractContextManager[Session]:
        self.opened += 1
        raise self.error


@dataclass
class RecordingSimulationService:
    reruns: list[ReportRerunInput] = field(default_factory=list)

    def rerun_report(self, rerun: ReportRerunInput) -> StartedReportRun:
        self.reruns.append(rerun)
        return StartedReportRun(report_run_id=uuid4())


def stored_rows(**report_columns: object) -> StoredReportRows:
    report = Report(
        id=REPORT_ID,
        label="Reform",
        country="us",
        tax_benefit_model_id=uuid4(),
        year=2026,
        inputs={},
        **report_columns,
    )
    return StoredReportRows(
        report=report,
        region_code="us",
        dataset_name=None,
        baseline_simulation=None,
        reform_simulation=None,
        run=None,
        budget_window_run=None,
        budget_window_years=(),
    )


def current_versions(country_id: str) -> PackageVersions:
    return CURRENT_VERSIONS


def test_a_rerun_without_the_simulation_service_reads_nothing() -> None:
    database_session = FailingDatabaseSession()
    service = V2StoredReportService(
        database_session,
        current_versions=current_versions,
    )

    with pytest.raises(SubmissionsNotConfiguredError):
        service.rerun_report(country_id="us", report_id=REPORT_ID, force=False)

    assert database_session.opened == 0


def test_a_rerun_whose_report_cannot_be_read_is_storage_unavailable() -> None:
    database_session = FailingDatabaseSession()
    simulation_service = RecordingSimulationService()
    service = V2StoredReportService(
        database_session,
        current_versions=current_versions,
        submissions=simulation_service,
    )

    with pytest.raises(ReportStorageError) as unavailable:
        service.rerun_report(country_id="us", report_id=REPORT_ID, force=True)

    assert unavailable.value.__cause__ is database_session.error
    assert simulation_service.reruns == []


def test_a_run_list_whose_report_cannot_be_read_is_storage_unavailable() -> None:
    database_session = FailingDatabaseSession()
    service = V2StoredReportService(
        database_session,
        current_versions=current_versions,
    )

    with pytest.raises(ReportStorageError) as unavailable:
        service.list_report_runs(country_id="us", report_id=REPORT_ID)

    assert unavailable.value.__cause__ is database_session.error


def test_a_window_run_with_no_year_lists_no_years_and_no_versions() -> None:
    window_run = BudgetWindowRun(
        id=uuid4(),
        created_at=STORED_AT,
        updated_at=STORED_AT,
        report_id=REPORT_ID,
        tax_benefit_model_version_id=uuid4(),
        trigger=ReportRunTrigger.MANUAL,
        recalculate=True,
        status=ReportRunStatus.PENDING,
    )

    runs = budget_window_runs_read(
        stored_rows(budget_window_size=2),
        [window_run],
        {},
        current_versions=CURRENT_VERSIONS,
    )

    assert runs.kind == "budget_window"
    (run,) = runs.runs
    assert run.id == window_run.id
    assert (run.trigger, run.recalculate, run.status) == ("manual", True, "pending")
    assert run.years == ()
    assert run.country_package_version is None
    assert run.policyengine_version is None
