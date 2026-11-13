"""Database inserts of users' report-run records."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import col

from policyengine_api.data.v2.models import UserReportRunAssociation

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.data.v2.models import ReportRunTrigger


def create_report_run_records(
    session: Session,
    *,
    user_id: UUID,
    report_run_ids: Sequence[UUID],
    requested_at: datetime,
    trigger: ReportRunTrigger,
) -> list[UUID]:
    """Record the user's request for each run they have no record of yet.

    A run the user already has a record of keeps it (``ON CONFLICT (user_id,
    report_run_id) DO NOTHING``). Return the runs this call recorded.
    """
    if not report_run_ids:
        return []
    statement = (
        insert(UserReportRunAssociation)
        .values(
            [
                {
                    "id": uuid4(),
                    "user_id": user_id,
                    "report_run_id": report_run_id,
                    "requested_at": requested_at,
                    "trigger": trigger,
                }
                for report_run_id in report_run_ids
            ]
        )
        .on_conflict_do_nothing(index_elements=["user_id", "report_run_id"])
        .returning(col(UserReportRunAssociation.report_run_id))
    )
    return list(session.scalars(statement).all())
