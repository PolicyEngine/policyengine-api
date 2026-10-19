"""Database inserts for v2 user-report associations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.data.v2.models import UserReportAssociation

if TYPE_CHECKING:
    from sqlmodel import Session

    from policyengine_api.services.v2.user_reports.types import UserReportCreationInput


def create_user_report(
    session: Session,
    association_input: UserReportCreationInput,
) -> UserReportAssociation:
    """Insert an association and return it with its database-generated fields loaded."""
    association = UserReportAssociation(**association_input.model_dump())
    session.add(association)
    session.flush()
    session.refresh(association)
    return association
