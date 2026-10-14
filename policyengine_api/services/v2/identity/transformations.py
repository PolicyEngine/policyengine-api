"""Pure transformations for v2 identity resolution."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from policyengine_api.data.v2.models import User, UserIdentity, UserType
from policyengine_api.services.v2.identity.types import ResolvedUser


LAST_SEEN_REFRESH_INTERVAL = timedelta(hours=1)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def refreshed_identity_email(identity: UserIdentity, email: str | None) -> str | None:
    """Keep a stored verified email when the current token carries none."""

    return identity.email if email is None else email


def identity_refresh_required(
    identity: UserIdentity,
    *,
    email: str | None,
    now: datetime,
) -> bool:
    """Write identity activity at most hourly, or when the email changes."""

    if refreshed_identity_email(identity, email) != identity.email:
        return True
    return _aware(now) - _aware(identity.last_seen_at) >= LAST_SEEN_REFRESH_INTERVAL


def standard_resolved_user(user_id: UUID, *, email: str | None) -> ResolvedUser:
    return ResolvedUser(user_id=user_id, email=email, user_type=UserType.STANDARD)


def unauthenticated_resolved_user(user: User) -> ResolvedUser:
    return ResolvedUser(user_id=user.id, email=None, user_type=UserType.UNAUTHENTICATED)


def converted_primary_country(user: User, *, country_id: str) -> str:
    """A converted user keeps any primary country, or takes the request's."""

    return user.primary_country or country_id
