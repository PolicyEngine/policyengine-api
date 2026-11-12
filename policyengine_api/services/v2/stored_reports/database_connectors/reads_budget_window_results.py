"""Database reads of the result rows a budget-window run's years hold."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import col, select

from policyengine_api.data.v2.models import BudgetSummary
from policyengine_api.services.v2.stored_reports.budget_window_results.types import (
    BudgetWindowResultRows,
    BudgetWindowYearRows,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.data.v2.models import Report, ReportRun


def read_budget_window_result_rows(
    session: Session,
    *,
    report: Report,
    year_runs: Sequence[ReportRun],
) -> BudgetWindowResultRows:
    """Return the budget summary rows of each year's report run, in one query.

    Each year comes with its report run's status and stored SPM receipts.
    The window they should cover is the report's ``year`` and
    ``budget_window_size``.
    """
    budget_rows: dict[UUID, list[BudgetSummary]] = {run.id: [] for run in year_runs}
    if budget_rows:
        for row in session.exec(
            select(BudgetSummary).where(
                col(BudgetSummary.report_run_id).in_(budget_rows)
            )
        ):
            budget_rows[row.report_run_id].append(row)
    return BudgetWindowResultRows(
        country_id=report.country,
        first_year=report.year,
        window_size=report.budget_window_size,
        years=tuple(
            BudgetWindowYearRows(
                year=run.year,
                status=run.status,
                spm_provenance=run.spm_provenance,
                budget_summary=tuple(budget_rows[run.id]),
            )
            for run in year_runs
            if run.year is not None
        ),
    )
