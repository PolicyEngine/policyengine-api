"""Database-independent checks for admins' email invitations and their acceptance."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.data.v2.models import INVITATION_USER_TYPES, UserType
from policyengine_api.services.v2.user_invitations.transformations import as_utc

if TYPE_CHECKING:
    from collections.abc import Collection
    from datetime import datetime
    from uuid import UUID

    from policyengine_api.data.v2.models import UserInvitation
    from policyengine_api.libs.auth0_management import Auth0UserProfile


class InvitationNotFoundError(LookupError):
    """Raised when no open invitation has an admin's requested ID (404)."""


class InvitationUnavailableError(Exception):
    """Raised when an invitation's token can't be accepted (410).

    Each subclass names one reason with its ``code``.
    """

    code = "invitation_unavailable"


class InvitationTokenNotFoundError(InvitationUnavailableError):
    """No invitation has the token, including a link replaced by a resend."""

    code = "invitation_not_found"


class InvitationRevokedError(InvitationUnavailableError):
    """The invitation was revoked, or replaced by a newer one to its address."""

    code = "invitation_revoked"


class InvitationExpiredError(InvitationUnavailableError):
    """The invitation's link expired."""

    code = "invitation_expired"


class InvitationAcceptedError(InvitationUnavailableError):
    """The invitation was already accepted."""

    code = "invitation_accepted"


class InviterNotAdminError(ValueError):
    """Raised when the admin who sent an invitation is no longer an admin (409)."""

    code = "inviter_not_admin"


class InvitationEmailNotVerifiedError(ValueError):
    """Raised when Auth0 has no verified email for the invitee (409)."""

    code = "email_not_verified"


class InvitationEmailMismatchError(PermissionError):
    """Raised when the invitee's verified email isn't the invited address (403)."""

    code = "email_mismatch"


class InvitationEmailUnavailableError(RuntimeError):
    """Raised when the invitee's email can't be read from Auth0 (503)."""

    code = "auth0_unavailable"


def require_invitation_user_type(user_type: UserType) -> UserType:
    """Return a type an invitation can grant, author or admin; raise otherwise."""
    if user_type not in INVITATION_USER_TYPES:
        msg = "An invitation grants the author or admin type"
        raise ValueError(msg)
    return user_type


def require_open_invitation(invitation: UserInvitation | None) -> UserInvitation:
    """Return an invitation that is neither accepted nor revoked."""
    if (
        invitation is None
        or invitation.accepted_at is not None
        or invitation.revoked_at is not None
    ):
        msg = "No pending invitation has this ID"
        raise InvitationNotFoundError(msg)
    return invitation


def require_acceptable_invitation(
    invitation: UserInvitation | None, *, now: datetime
) -> UserInvitation:
    """Return the token's invitation if it is open and unexpired; raise otherwise."""
    if invitation is None:
        msg = "This invitation link is not valid; ask for a new invitation"
        raise InvitationTokenNotFoundError(msg)
    if invitation.revoked_at is not None:
        msg = "This invitation was withdrawn; ask for a new invitation"
        raise InvitationRevokedError(msg)
    if invitation.accepted_at is not None:
        msg = "This invitation was already accepted"
        raise InvitationAcceptedError(msg)
    if as_utc(invitation.expires_at) <= now:
        msg = "This invitation expired; ask for a new invitation"
        raise InvitationExpiredError(msg)
    return invitation


def require_inviter_admin(
    invited_by_user_id: UUID | None, admin_user_ids: Collection[UUID]
) -> None:
    """Refuse an invitation whose inviting admin is no longer among the admins."""
    if invited_by_user_id is None or invited_by_user_id not in admin_user_ids:
        msg = (
            "The admin who sent this invitation is no longer an admin; ask for "
            "a new invitation"
        )
        raise InviterNotAdminError(msg)


def require_verified_email(profile: Auth0UserProfile | None) -> str:
    """Return the invitee's verified Auth0 email, or refuse until it is verified."""
    if profile is None or not profile.email_verified or not profile.email:
        msg = (
            "Your email address isn't verified yet: open the verification "
            "email from PolicyEngine's sign-in service, then try again"
        )
        raise InvitationEmailNotVerifiedError(msg)
    return profile.email


def require_invited_email(invited_email: str, verified_email: str) -> None:
    """Refuse a verified email that isn't the invited address, ignoring case."""
    if invited_email.lower() != verified_email.lower():
        msg = (
            "This invitation was sent to another email address; sign in with "
            "the address it was sent to"
        )
        raise InvitationEmailMismatchError(msg)


def grants_new_type(current_user_type: UserType, invited_user_type: UserType) -> bool:
    """Say whether accepting raises the type: an invitation never lowers one."""
    order = tuple(UserType)
    return order.index(invited_user_type) > order.index(current_user_type)
