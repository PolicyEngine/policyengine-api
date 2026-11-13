"""Database reads of what a requesting user sees of reports.

A user's saved report gives a report its label and description, and the
user's newest request for one of a report's runs
(``user_report_run_associations``) is the run a read answers by default.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import aliased
from sqlmodel import col

from policyengine_api.data.v2.models import (
    BudgetWindowRun,
    ReportRun,
    UserReportAssociation,
    UserReportRunAssociation,
)

if TYPE_CHECKING:
    from collections.abc import Collection
    from uuid import UUID

    from sqlmodel import Session


def read_saved_report_labels(
    session: Session, *, user_id: UUID, report_ids: Collection[UUID]
) -> dict[UUID, tuple[str | None, str | None]]:
    """Return each report's name and description from the user's saved report.

    A user with several saved reports of one report gives the one saved last
    (ties to the larger ID). Reports the user hasn't saved are absent.
    """
    newest_saved_first = (
        func.row_number()
        .over(
            partition_by=col(UserReportAssociation.report_id),
            order_by=(
                col(UserReportAssociation.created_at).desc(),
                col(UserReportAssociation.id).desc(),
            ),
        )
        .label("newest_saved_first")
    )
    ranked = (
        select(
            col(UserReportAssociation.report_id),
            col(UserReportAssociation.name),
            col(UserReportAssociation.description),
            newest_saved_first,
        )
        .where(
            col(UserReportAssociation.user_id) == user_id,
            col(UserReportAssociation.report_id).in_(report_ids),
        )
        .subquery("ranked_saved_reports")
    )
    statement = select(ranked.c.report_id, ranked.c.name, ranked.c.description).where(
        ranked.c.newest_saved_first == 1
    )
    return {
        report_id: (name, description)
        for report_id, name, description in session.execute(statement).all()
    }


def read_requested_report_runs(
    session: Session, *, user_id: UUID, report_ids: Collection[UUID]
) -> dict[UUID, ReportRun]:
    """Return, by report, the report run of the user's newest request for one.

    Newest is requested last, ties going to the run with the larger ID. For a
    budget window the run is a year's, naming its budget-window run. Reports
    the user never asked to run are absent.
    """
    newest_requested_first = (
        func.row_number()
        .over(
            partition_by=col(ReportRun.report_id),
            order_by=(
                col(UserReportRunAssociation.requested_at).desc(),
                col(ReportRun.id).desc(),
            ),
        )
        .label("newest_requested_first")
    )
    ranked = (
        select(ReportRun, newest_requested_first)
        .join(
            UserReportRunAssociation,
            col(UserReportRunAssociation.report_run_id) == ReportRun.id,
        )
        .where(
            col(UserReportRunAssociation.user_id) == user_id,
            col(ReportRun.report_id).in_(report_ids),
        )
        .subquery("ranked_requested_runs")
    )
    requested_run = aliased(ReportRun, ranked)
    statement = select(requested_run).where(ranked.c.newest_requested_first == 1)
    return {run.report_id: run for run in session.scalars(statement).all()}


def read_budget_window_runs_by_id(
    session: Session, *, budget_window_run_ids: Collection[UUID]
) -> dict[UUID, BudgetWindowRun]:
    """Return the budget-window runs with these IDs, by ID."""
    if not budget_window_run_ids:
        return {}
    statement = select(BudgetWindowRun).where(
        col(BudgetWindowRun.id).in_(budget_window_run_ids)
    )
    return {window_run.id: window_run for window_run in session.scalars(statement)}
