"""Database reads of admins' email invitations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func
from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import UserInvitation

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy import ColumnElement


def _open() -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    """Return the conditions of an invitation neither accepted nor revoked."""
    return (
        col(UserInvitation.accepted_at).is_(None),
        col(UserInvitation.revoked_at).is_(None),
    )


def read_open_invitations(
    session: Session, *, offset: int, limit: int
) -> list[UserInvitation]:
    """Return a page of invitations neither accepted nor revoked, newest first."""
    return list(
        session.exec(
            select(UserInvitation)
            .where(*_open())
            .order_by(col(UserInvitation.created_at).desc(), col(UserInvitation.id))
            .offset(offset)
            .limit(limit)
        ).all()
    )


def read_open_invitations_to(session: Session, email: str) -> list[UserInvitation]:
    """Return the open invitations to ``email``, compared whole ignoring case.

    Each row is locked (``FOR UPDATE``) until the transaction ends.
    """
    return list(
        session.exec(
            select(UserInvitation)
            .where(func.lower(col(UserInvitation.email)) == email.lower(), *_open())
            .order_by(col(UserInvitation.id))
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )


def read_invitation(
    session: Session, invitation_id: UUID, *, for_update: bool = False
) -> UserInvitation | None:
    """Return the invitation with this ID, or None.

    ``for_update`` locks the row (``FOR UPDATE``) until the transaction ends.
    """
    statement = select(UserInvitation).where(UserInvitation.id == invitation_id)
    if for_update:
        statement = statement.with_for_update()
    return session.exec(
        statement.execution_options(populate_existing=True)
    ).one_or_none()


def read_invitation_by_token_hash(
    session: Session, token_hash: str
) -> UserInvitation | None:
    """Return the invitation whose token has this hash, locked until the end."""
    return session.exec(
        select(UserInvitation)
        .where(UserInvitation.token_hash == token_hash)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one_or_none()
