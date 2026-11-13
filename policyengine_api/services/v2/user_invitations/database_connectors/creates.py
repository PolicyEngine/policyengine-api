"""Database inserts of admins' email invitations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.data.v2.models import UserInvitation

if TYPE_CHECKING:
    from sqlmodel import Session

    from policyengine_api.services.v2.user_invitations.types import NewInvitation


def create_user_invitation(session: Session, new: NewInvitation) -> UserInvitation:
    """Store one invitation, with its token's hash."""
    invitation = UserInvitation(
        email=new.email,
        user_type=new.user_type.value,
        token_hash=new.token_hash,
        invited_by_user_id=new.invited_by_user_id,
        created_at=new.created_at,
        expires_at=new.expires_at,
    )
    session.add(invitation)
    session.flush()
    return invitation
