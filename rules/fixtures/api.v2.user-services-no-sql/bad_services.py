"""Proof fixture: a user service that queries rows itself. The rule must reject it."""

from sqlmodel import Session, select

from policyengine_api.data.v2.models import UserPolicy


def list_user_policies(session: Session, user_id: str) -> list[UserPolicy]:
    """List the user's policies by querying the rows itself."""
    return list(session.exec(select(UserPolicy).where(UserPolicy.user_id == user_id)))
