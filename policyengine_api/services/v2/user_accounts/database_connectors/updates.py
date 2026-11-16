"""Database updates for signed-in v2 accounts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from sqlmodel import Session

    from policyengine_api.data.v2.models import User, UserTypeChange


def update_account_user(
    session: Session,
    user: User,
    values: Mapping[str, Any],
) -> User:
    """Set only the given fields on the user and return it reloaded."""
    for field_name, value in values.items():
        setattr(user, field_name, value)
    session.add(user)
    session.flush()
    session.refresh(user)
    return user


def dismiss_user_type_change(
    session: Session, change: UserTypeChange, *, dismissed_at: datetime
) -> UserTypeChange:
    """Record when the user dismissed the app's notice of a type change."""
    change.dismissed_at = dismissed_at
    session.add(change)
    session.flush()
    return change
