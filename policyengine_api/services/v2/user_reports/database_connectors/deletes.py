"""Database deletes for v2 user-report associations."""

from __future__ import annotations

from sqlmodel import Session

from policyengine_api.data.v2.models import UserReportAssociation


def delete_user_report(
    session: Session,
    association: UserReportAssociation,
) -> None:
    session.delete(association)
    session.flush()
