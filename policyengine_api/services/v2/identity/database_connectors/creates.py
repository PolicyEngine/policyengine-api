"""Database inserts used by v2 identity provisioning."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col

from policyengine_api.data.v2.models import User, UserIdentity, UserType


def create_provisioned_user(session: Session, *, primary_country: str) -> User:
    user = User(primary_country=primary_country, user_type=UserType.STANDARD.value)
    session.add(user)
    session.flush()
    return user


def create_unauthenticated_user(session: Session, *, user_id: UUID) -> bool:
    """Insert an unauthenticated user unless a user with its ID already exists.

    Returns whether this call inserted the row.
    """

    return (
        session.execute(
            insert(User)
            .values(id=user_id, user_type=UserType.UNAUTHENTICATED.value)
            .on_conflict_do_nothing(index_elements=[col(User.id)])
            .returning(col(User.id))
        ).scalar_one_or_none()
        is not None
    )


def create_user_identity(
    session: Session,
    *,
    user_id: UUID,
    issuer: str,
    subject: str,
    email: str | None,
    seen_at: datetime,
) -> UUID | None:
    """Insert one identity, returning its user unless another request won."""

    return session.execute(
        insert(UserIdentity)
        .values(
            user_id=user_id,
            issuer=issuer,
            subject=subject,
            email=email,
            last_seen_at=seen_at,
        )
        .on_conflict_do_nothing(constraint="uq_user_identities_issuer_subject")
        .returning(col(UserIdentity.user_id))
    ).scalar_one_or_none()
