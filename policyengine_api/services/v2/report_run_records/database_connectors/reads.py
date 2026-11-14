"""Database reads of users' report-run records."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlmodel import col

from policyengine_api.data.v2.models import (
    ReportRun,
    UserReportAssociation,
    UserReportRunAssociation,
)
from policyengine_api.services.v2.report_run_records.types import ReportRunRecordRead

if TYPE_CHECKING:
    from collections.abc import Collection
    from datetime import datetime
    from uuid import UUID

    from sqlmodel import Session


def read_report_ids_of_runs(
    session: Session, *, report_run_ids: Collection[UUID]
) -> set[UUID]:
    """Return the reports these report runs belong to."""
    if not report_run_ids:
        return set()
    statement = select(col(ReportRun.report_id)).where(
        col(ReportRun.id).in_(report_run_ids)
    )
    return set(session.scalars(statement).all())


def read_saved_report_ids(session: Session, *, user_id: UUID) -> set[UUID]:
    """Return the detailed-save reports the user's saved reports name."""
    statement = select(col(UserReportAssociation.report_id)).where(
        col(UserReportAssociation.user_id) == user_id,
        col(UserReportAssociation.report_id).is_not(None),
    )
    return {report_id for report_id in session.scalars(statement) if report_id}


def read_report_run_records(
    session: Session, *, user_id: UUID
) -> list[ReportRunRecordRead]:
    """Return every report-run record of the user, in no set order."""
    statement = select(
        col(UserReportRunAssociation.report_run_id),
        col(UserReportRunAssociation.requested_at),
        col(UserReportRunAssociation.trigger),
    ).where(col(UserReportRunAssociation.user_id) == user_id)
    return [
        ReportRunRecordRead(
            report_run_id=report_run_id, requested_at=requested_at, trigger=trigger
        )
        for report_run_id, requested_at, trigger in session.execute(statement).all()
    ]


def read_newest_report_request(
    session: Session, *, user_id: UUID, report_id: UUID
) -> datetime | None:
    """Return the user's newest request time among the report's runs, or None."""
    statement = (
        select(func.max(col(UserReportRunAssociation.requested_at)))
        .join(ReportRun, col(ReportRun.id) == UserReportRunAssociation.report_run_id)
        .where(
            col(UserReportRunAssociation.user_id) == user_id,
            col(ReportRun.report_id) == report_id,
        )
    )
    newest_request: datetime | None = session.execute(statement).scalar_one()
    return newest_request


def read_budget_window_year_run_ids(
    session: Session, *, budget_window_run_id: UUID
) -> list[UUID]:
    """Return the report run of each year of the budget-window run, in year order."""
    statement = (
        select(col(ReportRun.id))
        .where(col(ReportRun.budget_window_run_id) == budget_window_run_id)
        .order_by(col(ReportRun.year), col(ReportRun.id))
    )
    return list(session.scalars(statement).all())
