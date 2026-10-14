"""Database deletes used by v2 identity conversion and account deletion."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete
from sqlmodel import Session, col

from policyengine_api.data.v2.models import User, UserType


def delete_unauthenticated_user(session: Session, *, user_id: UUID) -> None:
    """Delete an unauthenticated user; its associations cascade.

    The statement matches only an unauthenticated row, so it never deletes a
    standard user, including one converted by a concurrent transaction.
    """

    session.execute(
        delete(User).where(
            col(User.id) == user_id,
            col(User.user_type) == UserType.UNAUTHENTICATED.value,
        )
    )
    session.flush()
