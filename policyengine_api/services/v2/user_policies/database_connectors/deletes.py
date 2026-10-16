"""Database deletes used by v2 user-policy operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlmodel import Session

    from policyengine_api.data.v2.models import User, UserPolicy


def delete_user_policy(session: Session, association: UserPolicy) -> None:
    """Delete an association row; the policy it points to is kept."""
    session.delete(association)
    session.flush()


def delete_transition_user(session: Session, user: User) -> None:
    """Delete a transition user that lost a race to map its v1 user id."""
    session.delete(user)
    session.flush()
