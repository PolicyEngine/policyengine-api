"""Database updates for mutable v2 user-report association fields."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from policyengine_api.data.v2.models.base import utc_now

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlmodel import Session

    from policyengine_api.data.v2.models import UserReportAssociation


def update_user_report(
    session: Session,
    association: UserReportAssociation,
    values: Mapping[str, Any],
) -> UserReportAssociation:
    """Set the given column values, bump ``updated_at`` and return the row."""
    for field_name, value in values.items():
        setattr(association, field_name, value)
    association.updated_at = utc_now()
    session.add(association)
    session.flush()
    session.refresh(association)
    return association
