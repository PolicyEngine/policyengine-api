"""Proof fixture: a user service that leaves queries to its connector.

The rule must accept it.
"""

from sqlmodel import Session

from policyengine_api.data.v2.models import UserPolicy
from policyengine_api.services.v2.user_policies.database_connectors import reads


def list_user_policies(session: Session, user_id: str) -> list[UserPolicy]:
    """List the user's policies through the read connector."""
    return reads.list_user_policies(session, user_id=user_id)
