"""Database updates of users' types."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlmodel import Session

    from policyengine_api.data.v2.models import User, UserType


def update_user_type(session: Session, user: User, *, user_type: UserType) -> User:
    """Store a signed-in user's new type."""
    user.user_type = user_type.value
    session.add(user)
    session.flush()
    return user
