"""Database reads of a v2 report's runs, and of a budget window's runs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlmodel import col

from policyengine_api.data.v2.models import BudgetWindowRun, ReportRun

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel import Session


def read_report_runs(session: Session, *, report_id: UUID) -> list[ReportRun]:
    """Return every run of the report, newest first.

    Newest is created last, ties broken by the larger ID, as for the report's
    newest run. Runs of a budget window's years are not the report's own
    runs, so they are left out.
    """
    statement = (
        select(ReportRun)
        .where(
            col(ReportRun.report_id) == report_id,
            col(ReportRun.budget_window_run_id).is_(None),
        )
        .order_by(col(ReportRun.created_at).desc(), col(ReportRun.id).desc())
    )
    return list(session.scalars(statement).all())


def read_budget_window_runs(
    session: Session, *, report_id: UUID
) -> list[BudgetWindowRun]:
    """Return every budget-window run of the report, newest first.

    Newest is created last, ties broken by the larger ID, as for the
    window's newest run. Each run's years are read separately
    (``reads.read_budget_window_years``).
    """
    statement = (
        select(BudgetWindowRun)
        .where(col(BudgetWindowRun.report_id) == report_id)
        .order_by(
            col(BudgetWindowRun.created_at).desc(), col(BudgetWindowRun.id).desc()
        )
    )
    return list(session.scalars(statement).all())


def read_report_run(
    session: Session, *, report_id: UUID, run_id: UUID
) -> ReportRun | None:
    """Return the report's own run ``run_id``, or None when it has no such run.

    A run of another report, or of a budget window's year, is not one of its
    own runs.
    """
    statement = select(ReportRun).where(
        col(ReportRun.id) == run_id,
        col(ReportRun.report_id) == report_id,
        col(ReportRun.budget_window_run_id).is_(None),
    )
    return session.scalars(statement).one_or_none()


def read_budget_window_run(
    session: Session, *, report_id: UUID, run_id: UUID
) -> BudgetWindowRun | None:
    """Return the report's budget-window run ``run_id``, or None without one.

    Its years are read separately (``reads.read_budget_window_years``).
    """
    statement = select(BudgetWindowRun).where(
        col(BudgetWindowRun.id) == run_id,
        col(BudgetWindowRun.report_id) == report_id,
    )
    return session.scalars(statement).one_or_none()
