"""Database selections used by v2 identity resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Session, select

from policyengine_api.data.v2.models import User, UserIdentity, UserType

if TYPE_CHECKING:
    from uuid import UUID


def read_user_identity(
    session: Session,
    *,
    issuer: str,
    subject: str,
) -> UserIdentity | None:
    return session.exec(
        select(UserIdentity).where(
            UserIdentity.issuer == issuer,
            UserIdentity.subject == subject,
        )
    ).one_or_none()


def read_user(
    session: Session,
    user_id: UUID,
    *,
    for_share: bool = False,
) -> User | None:
    """Read one user, optionally holding ``FOR SHARE`` until the transaction ends.

    The share lock lets concurrent writers of one unauthenticated user proceed
    together but waits for a conversion holding ``FOR UPDATE``, then re-reads
    the row as that conversion committed it.
    """
    statement = select(User).where(User.id == user_id)
    if for_share:
        statement = statement.with_for_update(read=True)
    return session.exec(
        statement.execution_options(populate_existing=True)
    ).one_or_none()


def read_unauthenticated_user_for_update(
    session: Session,
    user_id: UUID,
) -> User | None:
    """Lock and return an unauthenticated user.

    A standard user is neither returned nor locked. A row converted by a
    concurrent transaction is re-checked once that transaction commits, so
    it is no longer returned.
    """
    return session.exec(
        select(User)
        .where(
            User.id == user_id,
            User.user_type == UserType.UNAUTHENTICATED.value,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one_or_none()
