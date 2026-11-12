"""Pure conversions for minimum user types and changes to users' types."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from policyengine_api.data.v2.models import UserType, UserTypeChangeSource
from policyengine_api.services.v2.identity.types import UserPrincipal
from policyengine_api.services.v2.user_types.types import (
    AdminUserRead,
    StoredAdminUser,
    StoredUserTypeChange,
    UserTypeChangeRead,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from uuid import UUID

    from policyengine_api.data.v2.models import User, UserIdentity, UserTypeChange
    from policyengine_api.libs.auth0_management import Auth0UserProfile
    from policyengine_api.services.v2.identity.types import (
        AccountPrincipal,
        ResolvedUser,
    )
    from policyengine_api.services.v2.user_accounts.types import AccountExport


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


def profile_subjects(
    identities: Sequence[UserIdentity], issuer: str | None
) -> tuple[str, ...]:
    """Return the identities' subjects from ``issuer``, in the order given.

    Without an issuer, no identity is a user of the profiles' tenant.
    """
    if issuer is None:
        return ()
    return tuple(
        identity.subject for identity in identities if identity.issuer == issuer
    )


def stored_admin_user(
    user: User, identities: Sequence[UserIdentity], issuer: str | None
) -> StoredAdminUser:
    """Describe a signed-in user as stored, with the subjects of its profiles."""
    return StoredAdminUser(
        read=admin_user_read(user, identities),
        profile_subjects=profile_subjects(identities, issuer),
    )


def stored_user_type_change(
    change: UserTypeChange,
    changed_by: User | None,
    changed_by_identities: Sequence[UserIdentity],
    issuer: str | None,
) -> StoredUserTypeChange:
    """Describe a recorded change as stored, with its admin's profile subjects."""
    return StoredUserTypeChange(
        read=user_type_change_read(change, changed_by, changed_by_identities),
        changed_by_profile_subjects=(
            ()
            if change.changed_by_user_id is None
            else profile_subjects(changed_by_identities, issuer)
        ),
    )


def profiles_of(
    subjects: Sequence[str], profiles: Mapping[str, Auth0UserProfile]
) -> list[Auth0UserProfile]:
    """Return the profiles found for these subjects, in the subjects' order."""
    return [profiles[subject] for subject in subjects if subject in profiles]


def profile_email(profiles: Sequence[Auth0UserProfile]) -> str | None:
    """Return the first verified email, else the first email, in profile order."""
    for profile in profiles:
        if profile.email is not None and profile.email_verified:
            return profile.email
    for profile in profiles:
        if profile.email is not None:
            return profile.email
    return None


def _profile_display_name(profiles: Sequence[Auth0UserProfile]) -> str | None:
    """Return the first full name that isn't an email address.

    Auth0 sets a password user's ``name`` to its email address, which is no
    name.
    """
    for profile in profiles:
        if profile.name is not None and "@" not in profile.name:
            return profile.name
    return None


def admin_user_read_with_profiles(
    read: AdminUserRead, profiles: Sequence[Auth0UserProfile]
) -> AdminUserRead:
    """Take the email and names from the user's profiles, newest identity first.

    A verified email comes before an unverified one, and stored values stay
    where the profiles have none. The given and family names come from the
    first profile that has either. Only when neither the profiles nor the
    stored user have a first or last name does a full name become the first
    name.
    """
    if not profiles:
        return read
    named = next(
        (
            profile
            for profile in profiles
            if profile.given_name is not None or profile.family_name is not None
        ),
        None,
    )
    first_name = read.first_name
    last_name = read.last_name
    if named is not None:
        first_name = named.given_name or first_name
        last_name = named.family_name or last_name
    if first_name is None and last_name is None:
        first_name = _profile_display_name(profiles)
    return replace(
        read,
        email=profile_email(profiles) or read.email,
        first_name=first_name,
        last_name=last_name,
    )


def user_type_change_read_with_profiles(
    read: UserTypeChangeRead, profiles: Sequence[Auth0UserProfile]
) -> UserTypeChangeRead:
    """Name the change's admin by the email of its profiles, else as stored."""
    if read.changed_by_user_id is None:
        return read
    return replace(
        read, changed_by_email=profile_email(profiles) or read.changed_by_email
    )


def saved_items_with_email(
    saved_items: AccountExport, email: str | None
) -> AccountExport:
    """Show ``email`` as the user's email in its saved items, when it has a user."""
    if saved_items.user is None:
        return saved_items
    return replace(saved_items, user=replace(saved_items.user, email=email))
