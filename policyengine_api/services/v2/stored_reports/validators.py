"""Database-independent checks of v2 reports and their runs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.stored_reports.economy_results.types import (
    EconomyResultUnreadableError,
)

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.data.v2.models import ReportRun
    from policyengine_api.services.v2.stored_reports.types import StoredReportRows


class StoredReportNotFoundError(LookupError):
    """No report has this ID in the requested country."""


class ReportStorageError(RuntimeError):
    """The detailed-save database could not be read."""


class CreatedReportUnreadableError(RuntimeError):
    """The simulation service created the report, but it could not be read back.

    The simulation service answered with the report's ID, so the report
    exists and submitting it again would create another. ``report_id`` and
    ``country_id`` say where to read it; the error's cause says why reading
    it back failed.
    """

    def __init__(self, *, report_id: UUID, country_id: str) -> None:
        """Name the created report and its country."""
        super().__init__(
            f"The simulation service created report {report_id} in country "
            f"{country_id!r}, but it could not be read back"
        )
        self.report_id = report_id
        self.country_id = country_id


class RerunReportUnreadableError(RuntimeError):
    """The simulation service started the report's new run, but it could not be read.

    The new run exists, so the caller reads the report rather than running
    it again. ``report_id`` and ``country_id`` say where to read it; the
    error's cause says why reading it back failed.
    """

    def __init__(self, *, report_id: UUID, country_id: str) -> None:
        """Name the report and its country."""
        super().__init__(
            f"The simulation service started a new run of report {report_id} in "
            f"country {country_id!r}, but the report could not be read back"
        )
        self.report_id = report_id
        self.country_id = country_id


def require_report(
    rows: StoredReportRows | None, *, report_id: UUID, country_id: str
) -> StoredReportRows:
    """Return the report's rows, or raise StoredReportNotFoundError for None."""
    if rows is None:
        msg = f"Report {report_id} was not found in country {country_id!r}"
        raise StoredReportNotFoundError(msg)
    return rows


def require_reform_run(report_run: ReportRun) -> UUID:
    """Return the reform simulation run an economy report run compares.

    Raise EconomyResultUnreadableError for a run with only a baseline.
    """
    if report_run.reform_simulation_run_id is None:
        msg = "the report run names no reform simulation run"
        raise EconomyResultUnreadableError(msg)
    return report_run.reform_simulation_run_id
