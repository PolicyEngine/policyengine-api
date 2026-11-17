"""Database updates of saved reports' last run times from users' requests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import or_, update
from sqlmodel import col

from policyengine_api.data.v2.models import UserReportAssociation

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlmodel import Session


def advance_saved_reports_last_run_at(
    session: Session, *, user_id: UUID, report_id: UUID, requested_at: datetime
) -> None:
    """Set the user's saved reports of the report to ``requested_at`` when later.

    A saved report whose ``last_run_at`` is already later, as one written by
    a concurrent newer request, keeps it, so the time never moves back; one
    with none takes ``requested_at``. ``updated_at`` is unchanged, since the
    user changed nothing.
    """
    session.execute(
        update(UserReportAssociation)
        .where(
            col(UserReportAssociation.user_id) == user_id,
            col(UserReportAssociation.report_id) == report_id,
            or_(
                col(UserReportAssociation.last_run_at).is_(None),
                col(UserReportAssociation.last_run_at) < requested_at,
            ),
        )
        .values(
            last_run_at=requested_at,
            updated_at=col(UserReportAssociation.updated_at),
        )
        .execution_options(synchronize_session=False)
    )


def update_saved_reports_last_run_at(
    session: Session,
    *,
    user_id: UUID,
    report_id: UUID,
    last_run_at: datetime | None,
) -> None:
    """Set the user's saved reports of the report to ``last_run_at``, even earlier.

    ``updated_at`` is unchanged, since the user changed nothing.
    """
    session.execute(
        update(UserReportAssociation)
        .where(
            col(UserReportAssociation.user_id) == user_id,
            col(UserReportAssociation.report_id) == report_id,
        )
        .values(
            last_run_at=last_run_at,
            updated_at=col(UserReportAssociation.updated_at),
        )
        .execution_options(synchronize_session=False)
    )
