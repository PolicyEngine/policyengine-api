"""Pure conversions for minimum user types and changes to users' types."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.data.v2.models import UserType, UserTypeChangeSource
from policyengine_api.services.v2.identity.types import UserPrincipal
from policyengine_api.services.v2.user_types.types import (
    AdminUserRead,
    UserTypeChangeRead,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from uuid import UUID

    from policyengine_api.data.v2.models import User, UserIdentity, UserTypeChange
    from policyengine_api.services.v2.identity.types import (
        AccountPrincipal,
        ResolvedUser,
    )


def caller_user_type(
    principal: AccountPrincipal, resolved: ResolvedUser | None
) -> UserType:
    """Return the type a caller acts with.

    A stored user acts with its stored type. A signed-in caller without a user
    yet is standard, as its first request provisions it; a signed-out browser
    without one is unauthenticated.
    """
    if resolved is not None:
        return resolved.user_type
    if isinstance(principal, UserPrincipal):
        return UserType.STANDARD
    return UserType.UNAUTHENTICATED


def identities_by_user(
    identities: Iterable[UserIdentity],
) -> dict[UUID, list[UserIdentity]]:
    """Group identities by user, keeping the order they were read in."""
    grouped: dict[UUID, list[UserIdentity]] = {}
    for identity in identities:
        grouped.setdefault(identity.user_id, []).append(identity)
    return grouped


def known_email(user: User | None, identities: Sequence[UserIdentity]) -> str | None:
    """Return the first identity email, newest identity first, else the user's own."""
    for identity in identities:
        if identity.email is not None:
            return identity.email
    return None if user is None else user.email


def admin_user_read(user: User, identities: Sequence[UserIdentity]) -> AdminUserRead:
    """Describe a signed-in user from its row and its identities, newest first."""
    return AdminUserRead(
        id=user.id,
        user_type=UserType(user.user_type),
        email=known_email(user, identities),
        first_name=user.first_name,
        last_name=user.last_name,
        primary_country=user.primary_country,
        created_at=user.created_at,
        last_seen_at=identities[0].last_seen_at if identities else None,
    )


def user_type_change_read(
    change: UserTypeChange,
    changed_by: User | None,
    changed_by_identities: Sequence[UserIdentity],
) -> UserTypeChangeRead:
    """Describe a recorded change, naming the admin who made it by email."""
    return UserTypeChangeRead(
        id=change.id,
        user_id=change.user_id,
        previous_user_type=UserType(change.previous_user_type),
        new_user_type=UserType(change.new_user_type),
        changed_by_user_id=change.changed_by_user_id,
        changed_by_email=(
            None
            if change.changed_by_user_id is None
            else known_email(changed_by, changed_by_identities)
        ),
        source=UserTypeChangeSource(change.source),
        created_at=change.created_at,
    )
