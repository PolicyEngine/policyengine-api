"""Database updates used by v2 identity resolution."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session

from policyengine_api.data.v2.models import UserIdentity


def update_user_identity_activity(
    session: Session,
    identity: UserIdentity,
    *,
    email: str | None,
    seen_at: datetime,
) -> UserIdentity:
    identity.email = email
    identity.last_seen_at = seen_at
    session.add(identity)
    session.flush()
    return identity
