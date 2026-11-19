"""Database deletes used by the operations on users' saved dynamics."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlmodel import Session

    from policyengine_api.data.v2.models import UserDynamic


def delete_user_dynamic(session: Session, saved_dynamic: UserDynamic) -> None:
    """Delete a saved dynamic; the dynamic it names is kept."""
    session.delete(saved_dynamic)
    session.flush()
