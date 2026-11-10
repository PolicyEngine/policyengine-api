"""Database reads for users' types and their recorded changes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, or_
from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import (
    User,
    UserIdentity,
    UserType,
    UserTypeChange,
)

if TYPE_CHECKING:
    from collections.abc import Collection
    from uuid import UUID


def read_admin_user_ids_for_update(session: Session) -> list[UUID]:
    """Lock every admin's row, in ID order, and return their IDs.

    Every change of a type, and every admin's account deletion, locks the
    admins first, in the same order, so they run one at a time and each counts
    the admins the ones before it left. The lock (``FOR NO KEY UPDATE``)
    doesn't hold up inserts whose foreign keys name an admin.
    """
    return list(
        session.exec(
            select(User.id)
            .where(User.user_type == UserType.ADMIN.value)
            .order_by(col(User.id))
            .with_for_update(key_share=True)
        ).all()
    )


def read_signed_in_user(
    session: Session, user_id: UUID, *, for_update: bool = False
) -> User | None:
    """Return the signed-in user with this ID, or None.

    An unauthenticated user is never returned. ``for_update`` locks the row
    (``FOR NO KEY UPDATE``) until the transaction ends.
    """
    statement = select(User).where(
        User.id == user_id, User.user_type != UserType.UNAUTHENTICATED.value
    )
    if for_update:
        statement = statement.with_for_update(key_share=True)
    return session.exec(
        statement.execution_options(populate_existing=True)
    ).one_or_none()


def read_signed_in_users(
    session: Session,
    *,
    email_contains: str | None,
    offset: int,
    limit: int,
) -> list[User]:
    """Return a page of signed-in users, newest first.

    With ``email_contains``, only users whose own email or any identity's
    email contains it, ignoring case; LIKE wildcards in it match literally.
    """
    statement = select(User).where(User.user_type != UserType.UNAUTHENTICATED.value)
    if email_contains is not None:
        identity_matches = (
            select(UserIdentity.id)
            .where(
                col(UserIdentity.user_id) == col(User.id),
                col(UserIdentity.email).icontains(email_contains, autoescape=True),
            )
            .exists()
        )
        statement = statement.where(
            or_(
                col(User.email).icontains(email_contains, autoescape=True),
                identity_matches,
            )
        )
    return list(
        session.exec(
            statement.order_by(col(User.created_at).desc(), col(User.id))
            .offset(offset)
            .limit(limit)
        ).all()
    )


def read_signed_in_users_with_email(session: Session, email: str) -> list[User]:
    """Return the signed-in users whose own or any identity's email is ``email``.

    The whole address is compared, ignoring case.
    """
    lowered = email.lower()
    identity_matches = (
        select(UserIdentity.id)
        .where(
            col(UserIdentity.user_id) == col(User.id),
            func.lower(col(UserIdentity.email)) == lowered,
        )
        .exists()
    )
    return list(
        session.exec(
            select(User)
            .where(
                User.user_type != UserType.UNAUTHENTICATED.value,
                or_(func.lower(col(User.email)) == lowered, identity_matches),
            )
            .order_by(col(User.id))
        ).all()
    )


def read_users(session: Session, user_ids: Collection[UUID]) -> list[User]:
    """Return the users with these IDs that still exist."""
    if not user_ids:
        return []
    return list(session.exec(select(User).where(col(User.id).in_(user_ids))).all())


def read_identities_newest_first(
    session: Session, user_ids: Collection[UUID]
) -> list[UserIdentity]:
    """Return these users' identities, each user's most recently seen first."""
    if not user_ids:
        return []
    return list(
        session.exec(
            select(UserIdentity)
            .where(col(UserIdentity.user_id).in_(user_ids))
            .order_by(
                col(UserIdentity.user_id),
                col(UserIdentity.last_seen_at).desc(),
                col(UserIdentity.id),
            )
        ).all()
    )


def read_user_type_changes(session: Session, user_id: UUID) -> list[UserTypeChange]:
    """Return a user's recorded type changes, newest first."""
    return list(
        session.exec(
            select(UserTypeChange)
            .where(UserTypeChange.user_id == user_id)
            .order_by(col(UserTypeChange.created_at).desc(), col(UserTypeChange.id))
        ).all()
    )
