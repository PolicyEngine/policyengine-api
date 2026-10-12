"""Database updates for signed-in v2 accounts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlmodel import Session

from policyengine_api.data.v2.models import User


def update_account_user(
    session: Session,
    user: User,
    values: Mapping[str, Any],
) -> User:
    for field_name, value in values.items():
        setattr(user, field_name, value)
    session.add(user)
    session.flush()
    session.refresh(user)
    return user
