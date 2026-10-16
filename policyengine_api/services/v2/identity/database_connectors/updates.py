"""Database updates used by v2 identity resolution and conversion."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import update
from sqlmodel import Session, col

from policyengine_api.data.v2.models import (
    User,
    UserHouseholdAssociation,
    UserIdentity,
    UserPolicy,
    UserReportAssociation,
    UserSimulationAssociation,
    UserType,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

USER_ASSOCIATION_TABLES = (
    UserPolicy,
    UserHouseholdAssociation,
    UserSimulationAssociation,
    UserReportAssociation,
)


def update_user_identity_activity(
    session: Session,
    identity: UserIdentity,
    *,
    email: str | None,
    seen_at: datetime,
) -> UserIdentity:
    """Record the identity's current email and the time it was last seen."""
    identity.email = email
    identity.last_seen_at = seen_at
    session.add(identity)
    session.flush()
    return identity


def update_user_to_standard(
    session: Session,
    user: User,
    *,
    primary_country: str,
) -> User:
    """Make an unauthenticated user standard, keeping its ID and associations."""
    user.user_type = UserType.STANDARD.value
    user.primary_country = primary_country
    session.add(user)
    session.flush()
    return user


def reassign_user_associations(
    session: Session,
    *,
    from_user_id: UUID,
    to_user_id: UUID,
) -> None:
    """Move every association row from one owner to another.

    Association IDs, contents, and timestamps are unchanged, so links between
    the moved rows (a report's ``user_policy_id`` and
    ``baseline_user_policy_id``) stay valid.
    """
    for table in USER_ASSOCIATION_TABLES:
        session.execute(
            update(table)
            .where(col(table.user_id) == from_user_id)
            .values(user_id=to_user_id, updated_at=col(table.updated_at))
            .execution_options(synchronize_session=False)
        )
    session.flush()
