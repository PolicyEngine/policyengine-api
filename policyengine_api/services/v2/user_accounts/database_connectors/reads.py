"""Database reads for signed-in v2 accounts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import User, UserIdentity, UserTypeChange

if TYPE_CHECKING:
    from uuid import UUID


def read_account_user(session: Session, user_id: UUID) -> User | None:
    """Return the v2 user with this id, or None."""
    return session.get(User, user_id)


def read_identity_subjects(
    session: Session,
    *,
    user_id: UUID,
    issuer: str,
) -> list[str]:
    """Return the user's sign-in subjects from ``issuer``, oldest identity first."""
    return list(
        session.exec(
            select(UserIdentity.subject)
            .where(UserIdentity.user_id == user_id, UserIdentity.issuer == issuer)
            .order_by(col(UserIdentity.created_at), col(UserIdentity.id))
        ).all()
    )


def read_latest_user_type_change(
    session: Session, user_id: UUID
) -> UserTypeChange | None:
    """Return the user's most recent recorded type change, or None."""
    return session.exec(
        select(UserTypeChange)
        .where(UserTypeChange.user_id == user_id)
        .order_by(col(UserTypeChange.created_at).desc(), col(UserTypeChange.id).desc())
        .limit(1)
    ).first()


def read_user_type_change(
    session: Session, type_change_id: UUID, *, user_id: UUID
) -> UserTypeChange | None:
    """Return this user's recorded type change with this ID, or None."""
    return session.exec(
        select(UserTypeChange).where(
            UserTypeChange.id == type_change_id, UserTypeChange.user_id == user_id
        )
    ).one_or_none()
