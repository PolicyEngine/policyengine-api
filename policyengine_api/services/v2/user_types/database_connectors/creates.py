"""Database inserts of recorded user-type changes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.data.v2.models import UserTypeChange

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.data.v2.models import UserType
    from policyengine_api.services.v2.user_types.types import UserTypeChangeOrigin


def create_user_type_change(
    session: Session,
    *,
    user_id: UUID,
    previous_user_type: UserType,
    new_user_type: UserType,
    origin: UserTypeChangeOrigin,
) -> UserTypeChange:
    """Record one change of a user's type."""
    change = UserTypeChange(
        user_id=user_id,
        changed_by_user_id=origin.changed_by_user_id,
        previous_user_type=previous_user_type.value,
        new_user_type=new_user_type.value,
        source=origin.source.value,
    )
    session.add(change)
    session.flush()
    return change
