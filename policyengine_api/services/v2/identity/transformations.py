"""Pure transformations for v2 identity resolution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from policyengine_api.data.v2.models import User, UserIdentity, UserType
from policyengine_api.services.v2.identity.types import ResolvedUser

if TYPE_CHECKING:
    from uuid import UUID

LAST_SEEN_REFRESH_INTERVAL = timedelta(hours=1)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


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
    """Describe a signed-in identity's standard user and its verified email."""
    return ResolvedUser(user_id=user_id, email=email, user_type=UserType.STANDARD)


def unauthenticated_resolved_user(user: User) -> ResolvedUser:
    """Describe a signed-out browser's user, which never has an email."""
    return ResolvedUser(user_id=user.id, email=None, user_type=UserType.UNAUTHENTICATED)


def converted_primary_country(user: User, *, country_id: str) -> str:
    """Return the user's primary country, or the request's if it has none."""
    return user.primary_country or country_id
