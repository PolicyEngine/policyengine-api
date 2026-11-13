"""Database reads of users' report-run records."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlmodel import col

from policyengine_api.data.v2.models import ReportRun, UserReportRunAssociation
from policyengine_api.services.v2.report_run_records.types import ReportRunRecordRead

if TYPE_CHECKING:
    from collections.abc import Collection
    from datetime import datetime
    from uuid import UUID

    from sqlmodel import Session


def read_newest_requests_by_report(
    session: Session, *, user_id: UUID, report_run_ids: Collection[UUID]
) -> dict[UUID, datetime]:
    """Return the user's newest request time among these runs, by each run's report."""
    if not report_run_ids:
        return {}
    statement = (
        select(
            col(ReportRun.report_id),
            func.max(col(UserReportRunAssociation.requested_at)),
        )
        .join(ReportRun, col(ReportRun.id) == UserReportRunAssociation.report_run_id)
        .where(
            col(UserReportRunAssociation.user_id) == user_id,
            col(UserReportRunAssociation.report_run_id).in_(report_run_ids),
        )
        .group_by(col(ReportRun.report_id))
    )
    return dict(session.execute(statement).tuples().all())


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
