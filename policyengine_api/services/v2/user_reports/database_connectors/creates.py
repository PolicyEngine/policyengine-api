"""Database inserts for v2 user-report associations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col

from policyengine_api.data.v2.models import UserReportAssociation
from policyengine_api.services.v2.user_reports.types import UserReportCreationInput


def create_user_report(
    session: Session,
    association_input: UserReportCreationInput,
) -> UserReportAssociation:
    association = UserReportAssociation(**association_input.model_dump())
    session.add(association)
    session.flush()
    session.refresh(association)
    return association


def import_user_report(
    session: Session,
    association_input: UserReportCreationInput,
) -> UUID | None:
    """Insert one imported association unless its client_ref already exists."""

    return session.execute(
        insert(UserReportAssociation)
        .values(**association_input.model_dump())
        .on_conflict_do_nothing(
            constraint="uq_user_report_associations_user_client_ref"
        )
        .returning(col(UserReportAssociation.id))
    ).scalar_one_or_none()
