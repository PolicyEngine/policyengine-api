"""Database-independent checks of v2 reports and their runs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.stored_reports.economy_results.types import (
    EconomyResultUnreadableError,
)
from policyengine_api.services.v2.stored_reports.transformations import report_kind

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.data.v2.models import ReportRun
    from policyengine_api.services.v2.stored_reports.types import StoredReportRows

READABLE_KIND = "economy"
KIND_NAMES = {"household": "a household report", "budget_window": "a budget window"}


class StoredReportNotFoundError(LookupError):
    """No report has this ID in the requested country."""


class ReportStorageError(RuntimeError):
    """The detailed-save database could not be read."""


class ReportKindUnsupportedError(ValueError):
    """The report is of a kind these routes do not read yet.

    Household reports and budget windows are stored in the same tables, and
    are read once their own routes exist.
    """


def require_report(
    rows: StoredReportRows | None, *, report_id: UUID, country_id: str
) -> StoredReportRows:
    """Return the report's rows, or raise StoredReportNotFoundError for None."""
    if rows is None:
        msg = f"Report {report_id} was not found in country {country_id!r}"
        raise StoredReportNotFoundError(msg)
    return rows


def require_economy_report(rows: StoredReportRows) -> None:
    """Raise ReportKindUnsupportedError unless the report is an economy report."""
    kind = report_kind(rows.report)
    if kind != READABLE_KIND:
        msg = (
            f"Report {rows.report.id} is {KIND_NAMES[kind]}, which this route "
            "cannot read yet"
        )
        raise ReportKindUnsupportedError(msg)


def require_reform_run(report_run: ReportRun) -> UUID:
    """Return the reform simulation run an economy report run compares.

    Raise EconomyResultUnreadableError for a run with only a baseline.
    """
    if report_run.reform_simulation_run_id is None:
        msg = "the report run names no reform simulation run"
        raise EconomyResultUnreadableError(msg)
    return report_run.reform_simulation_run_id
