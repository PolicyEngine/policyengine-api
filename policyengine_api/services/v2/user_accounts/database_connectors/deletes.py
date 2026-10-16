"""Database deletes for signed-in v2 accounts.

``legacy_user_mappings`` restricts user deletion, so its rows are removed
first. Deleting the user then cascades to identities and every association.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete
from sqlmodel import Session, col

from policyengine_api.data.v2.models import LegacyUserMapping, User

if TYPE_CHECKING:
    from uuid import UUID


def delete_account_legacy_user_mappings(session: Session, *, user_id: UUID) -> None:
    """Delete the v1 user mappings that would otherwise block deleting the user."""
    session.execute(
        delete(LegacyUserMapping).where(col(LegacyUserMapping.user_id) == user_id)
    )
    session.flush()


def delete_account_user(session: Session, *, user_id: UUID) -> None:
    """Delete the user; its identities and every association cascade with it."""
    session.execute(delete(User).where(col(User.id) == user_id))
    session.flush()
