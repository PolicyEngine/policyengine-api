"""Database deletes used by v2 user-policy association operations."""

from __future__ import annotations

from sqlmodel import Session

from policyengine_api.data.v2.models import User, UserPolicy


def delete_user_policy(session: Session, association: UserPolicy) -> None:
    """Delete one association and flush its database cascades."""

    session.delete(association)
    session.flush()


def delete_transition_user(session: Session, user: User) -> None:
    """Delete an unreferenced transition user after a mapping conflict."""

    session.delete(user)
    session.flush()
