"""Database inserts of users' report-run records."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import col

from policyengine_api.data.v2.models import UserReportRunAssociation

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.services.v2.report_run_records.types import (
        ReportRunRecordRead,
    )


def create_report_run_records(
    session: Session, *, user_id: UUID, records: Sequence[ReportRunRecordRead]
) -> list[UUID]:
    """Record each request for the user whose run they have no record of yet.

    Each row takes its record's run, ``requested_at`` and ``trigger``, with a
    new ID. A run the user already has a record of keeps that record (``ON
    CONFLICT (user_id, report_run_id) DO NOTHING``). Return the runs this
    call recorded.
    """
    if not records:
        return []
    statement = (
        insert(UserReportRunAssociation)
        .values(
            [
                {
                    "id": uuid4(),
                    "user_id": user_id,
                    "report_run_id": record.report_run_id,
                    "requested_at": record.requested_at,
                    "trigger": record.trigger,
                }
                for record in records
            ]
        )
        .on_conflict_do_nothing(index_elements=["user_id", "report_run_id"])
        .returning(col(UserReportRunAssociation.report_run_id))
    )
    return list(session.scalars(statement).all())
