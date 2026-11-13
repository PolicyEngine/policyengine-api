"""Pure conversions for admins' email invitations."""

from __future__ import annotations

import hashlib
from datetime import UTC
from typing import TYPE_CHECKING

from policyengine_api.data.v2.models import UserType
from policyengine_api.services.v2.user_invitations.types import AdminInvitationRead

if TYPE_CHECKING:
    from datetime import datetime

    from policyengine_api.data.v2.models import UserInvitation


def invitation_token_hash(token: str) -> str:
    """Return the SHA-256 digest of a token in hexadecimal, as it is stored."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def as_utc(moment: datetime) -> datetime:
    """Return an aware UTC time; a naive one (from SQLite) is read as UTC."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def admin_invitation_read(
    invitation: UserInvitation, *, now: datetime
) -> AdminInvitationRead:
    """Describe a stored invitation for admins, as of ``now``."""
    expires_at = as_utc(invitation.expires_at)
    return AdminInvitationRead(
        id=invitation.id,
        email=invitation.email,
        user_type=UserType(invitation.user_type),
        invited_by_user_id=invitation.invited_by_user_id,
        created_at=as_utc(invitation.created_at),
        expires_at=expires_at,
        expired=expires_at <= now,
        last_sent_at=(
            None if invitation.last_sent_at is None else as_utc(invitation.last_sent_at)
        ),
        last_send_error=invitation.last_send_error,
    )
