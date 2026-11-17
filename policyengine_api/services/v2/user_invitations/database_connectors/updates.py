"""Database updates of admins' email invitations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.data.v2.models import UserInvitation


def _store(session: Session, invitation: UserInvitation) -> UserInvitation:
    session.add(invitation)
    session.flush()
    return invitation


def revoke_invitation(
    session: Session, invitation: UserInvitation, *, revoked_at: datetime
) -> UserInvitation:
    """Mark an open invitation revoked, so its link stops working."""
    invitation.revoked_at = revoked_at
    return _store(session, invitation)


def renew_invitation(
    session: Session,
    invitation: UserInvitation,
    *,
    token_hash: str,
    expires_at: datetime,
    invited_by_user_id: UUID,
) -> UserInvitation:
    """Give an open invitation a new token, expiry and inviting admin.

    Its last send is cleared, since it was for the earlier token.
    """
    invitation.token_hash = token_hash
    invitation.expires_at = expires_at
    invitation.invited_by_user_id = invited_by_user_id
    invitation.last_sent_at = None
    invitation.last_send_error = None
    return _store(session, invitation)


def record_invitation_send(
    session: Session,
    invitation: UserInvitation,
    *,
    sent_at: datetime | None,
    send_error: str | None,
) -> UserInvitation:
    """Record the last send of an invitation's email: its time, or its failure."""
    invitation.last_sent_at = sent_at
    invitation.last_send_error = send_error
    return _store(session, invitation)


def accept_invitation(
    session: Session,
    invitation: UserInvitation,
    *,
    accepted_at: datetime,
    accepted_by_user_id: UUID,
) -> UserInvitation:
    """Mark an invitation accepted by a user."""
    invitation.accepted_at = accepted_at
    invitation.accepted_by_user_id = accepted_by_user_id
    return _store(session, invitation)
