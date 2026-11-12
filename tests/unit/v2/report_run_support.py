"""A stand-in report service that also runs reports again and lists their runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from policyengine_api.services.v2.stored_reports.types import (
    BudgetWindowRunsRead,
    ReportRunsRead,
)
from tests.unit.v2.budget_window_report_support import (
    BUDGET_WINDOW_REPORT_ID,
    budget_window_run_read,
)
from tests.unit.v2.stored_report_support import (
    CREATED_AT,
    CURRENT_VERSIONS,
    REPORT_ID,
    FakeReportService,
    report_run_read,
)

if TYPE_CHECKING:
    from policyengine_api.services.v2.stored_reports.types import (
        StoredReportRead,
        StoredReportRunsRead,
    )

NEW_RUN_ID = UUID("00000000-0000-0000-0000-00000000a00b")
NEW_WINDOW_RUN_ID = UUID("00000000-0000-0000-0000-00000000a10b")


def report_runs_read() -> ReportRunsRead:
    """Return a report's two runs, newest first: a re-run on the current versions."""
    return ReportRunsRead(
        report_id=REPORT_ID,
        kind="economy",
        runs=(
            report_run_read(
                id=NEW_RUN_ID,
                status="pending",
                trigger="manual",
                country_package_version=CURRENT_VERSIONS.country_package_version,
                policyengine_version=CURRENT_VERSIONS.policyengine_version,
                created_at=CREATED_AT + timedelta(days=3),
                started_at=None,
                completed_at=None,
            ),
            report_run_read(),
        ),
        current_versions=CURRENT_VERSIONS,
    )


def budget_window_runs_read() -> BudgetWindowRunsRead:
    """Return a budget window's two runs, newest first: a forced re-run, pending."""
    return BudgetWindowRunsRead(
        report_id=BUDGET_WINDOW_REPORT_ID,
        kind="budget_window",
        runs=(
            budget_window_run_read(
                id=NEW_WINDOW_RUN_ID,
                status="pending",
                trigger="manual",
                recalculate=True,
                country_package_version=CURRENT_VERSIONS.country_package_version,
                policyengine_version=CURRENT_VERSIONS.policyengine_version,
                created_at=CREATED_AT + timedelta(days=3),
                started_at=None,
                completed_at=None,
            ),
            budget_window_run_read(),
        ),
        current_versions=CURRENT_VERSIONS,
    )


@dataclass
class FakeReportRunService(FakeReportService):
    """Answer with ``report`` or ``runs``, or raise ``error``, recording each call.

    A re-run answers ``rerun`` when it is set, and ``report`` otherwise.
    """

    runs: StoredReportRunsRead = field(default_factory=report_runs_read)
    rerun: StoredReportRead | None = None

    def rerun_report(
        self, *, country_id: str, report_id: UUID, force: bool
    ) -> StoredReportRead:
        self._answer(
            "rerun_report", country_id=country_id, report_id=report_id, force=force
        )
        return self.report if self.rerun is None else self.rerun

    def list_report_runs(
        self, *, country_id: str, report_id: UUID
    ) -> StoredReportRunsRead:
        self._answer("list_report_runs", country_id=country_id, report_id=report_id)
        return self.runs
