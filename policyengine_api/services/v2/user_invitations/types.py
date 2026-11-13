"""Framework-independent data for admins' email invitations and their acceptance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from policyengine_api.query_parameters import DEFAULT_QUERY_LIMIT, MAXIMUM_QUERY_LIMIT

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from policyengine_api.data.v2.models import UserType

# How long an invitation's link works after it was created or last resent.
INVITATION_LIFETIME = timedelta(days=7)
# The random bytes in each invitation's token; it is sent URL-safe base64.
INVITATION_TOKEN_BYTES = 32

# One email address: an @ with text on both sides, and no whitespace, < or >.
InvitationEmailAddress = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=320,
        pattern=r"^[^@\s<>]+@[^@\s<>]+$",
    ),
]
# The token from an invitation's link, as the app sends it back.
InvitationToken = Annotated[str, StringConstraints(min_length=1, max_length=256)]


class AdminInvitationSearch(BaseModel):
    """Which page of open invitations an admin lists."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=DEFAULT_QUERY_LIMIT, ge=1, le=MAXIMUM_QUERY_LIMIT)


@dataclass(frozen=True)
class NewInvitation:
    """An invitation to store: only its token's hash, never the token."""

    email: str
    user_type: UserType
    token_hash: str
    invited_by_user_id: UUID
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class AdminInvitationRead:
    """An invitation as admins see it."""

    id: UUID
    email: str
    user_type: UserType
    # The admin who created or last resent it; None once that account is gone.
    invited_by_user_id: UUID | None
    created_at: datetime
    expires_at: datetime
    # Whether expires_at has passed: it can't be accepted, but can be resent.
    expired: bool
    # When the email with the current link was sent; None when it wasn't.
    last_sent_at: datetime | None
    # Why the last send failed, as a short identifier; None after a success.
    last_send_error: str | None


@dataclass(frozen=True)
class AdminInvitationPage:
    """One page of open invitations, newest first."""

    items: tuple[AdminInvitationRead, ...]
    offset: int
    limit: int
    has_more: bool


@dataclass(frozen=True)
class InvitationAcceptance:
    """The invitee's type after accepting, and before."""

    user_type: UserType
    previous_user_type: UserType
    # False when the user already had the invited type or a higher one.
    type_changed: bool
