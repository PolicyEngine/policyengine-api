"""Framework-independent data for minimum user types and changes to users' types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from policyengine_api.data.v2.models import UserType, UserTypeChangeSource
    from policyengine_api.libs.auth0_management import UserProfileReader

DEFAULT_ADMIN_USER_LIMIT = 100
MAXIMUM_ADMIN_USER_LIMIT = 500
# An email search is refused when more Auth0 users than this match its text:
# reading them all would need too many Management API requests.
MAXIMUM_EMAIL_SEARCH_MATCHES = 200

EmailSearchText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=320)
]


class AdminUserSearch(BaseModel):
    """Which signed-in users an admin lists: part of an email, and one page."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Matched case-insensitively against any part of a user's stored emails,
    # and of its Auth0 email when user profiles are configured; a LIKE or
    # Lucene wildcard in it is matched literally.
    email: EmailSearchText | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(
        default=DEFAULT_ADMIN_USER_LIMIT, ge=1, le=MAXIMUM_ADMIN_USER_LIMIT
    )


@dataclass(frozen=True)
class AdminUserRead:
    """A signed-in user as admins see it."""

    id: UUID
    user_type: UserType
    # Its Auth0 email when user profiles are configured and Auth0 has one;
    # otherwise the stored email of the user's most recently seen sign-in
    # identity that has one, else the email stored on the user.
    email: str | None
    first_name: str | None
    last_name: str | None
    primary_country: str | None
    created_at: datetime
    # When the user's most recently seen sign-in identity was last seen.
    last_seen_at: datetime | None


@dataclass(frozen=True)
class AdminUserPage:
    """One page of signed-in users, newest first."""

    items: tuple[AdminUserRead, ...]
    offset: int
    limit: int
    has_more: bool


@dataclass(frozen=True)
class UserTypeChangeRead:
    """One recorded change of a signed-in user's type."""

    id: UUID
    user_id: UUID
    previous_user_type: UserType
    new_user_type: UserType
    # Empty for a change the type script made, or once the admin is deleted.
    changed_by_user_id: UUID | None
    changed_by_email: str | None
    source: UserTypeChangeSource
    created_at: datetime


@dataclass(frozen=True)
class RequestedUserType:
    """The type a change asks for, and the type its requester last read.

    ``expected_user_type`` is None for the type script, which skips the
    comparison with a type read earlier; the last-admin rule still applies.
    """

    user_type: UserType
    expected_user_type: UserType | None


@dataclass(frozen=True)
class UserTypeChangeOrigin:
    """Who changed a user's type, and through what."""

    # Empty for the type script.
    changed_by_user_id: UUID | None
    source: UserTypeChangeSource


@dataclass(frozen=True)
class ScriptedUserTypeChange:
    """What the type script did: the user as it is now, and its type before."""

    user: AdminUserRead
    previous_user_type: UserType


@dataclass(frozen=True)
class UserProfileSource:
    """The Auth0 tenant admins' reads take users' emails and names from.

    ``reader`` reads users' emails and names from it when an admin asks; its
    subjects are the tenant's user IDs.

    ``issuer`` is the signed-in users' token issuer, normalized with a
    trailing slash as identities store it: only identities from it are users
    of that tenant, so only they are looked up.
    """

    issuer: str
    reader: UserProfileReader


@dataclass(frozen=True)
class IdentitySubjects:
    """Sign-in subjects from one issuer."""

    issuer: str
    subjects: tuple[str, ...]


@dataclass(frozen=True)
class StoredAdminUser:
    """A signed-in user as stored, and the subjects to read its profile with."""

    read: AdminUserRead
    # The user's subjects from the users' issuer, most recently seen first.
    profile_subjects: tuple[str, ...]


@dataclass(frozen=True)
class StoredUserTypeChange:
    """A recorded change as stored, and the subjects of the admin who made it."""

    read: UserTypeChangeRead
    # The admin's subjects from the users' issuer, most recently seen first.
    changed_by_profile_subjects: tuple[str, ...]
