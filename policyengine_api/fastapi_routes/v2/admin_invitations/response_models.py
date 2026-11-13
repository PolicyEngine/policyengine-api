"""Strict HTTP response models for admins' email invitation routes."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from policyengine_api.services.v2.user_invitations.types import (
        AdminInvitationPage,
        AdminInvitationRead,
    )


class StrictInvitationAPIModel(BaseModel):
    """Base for invitation responses; rejects unknown fields."""

    model_config = ConfigDict(extra="forbid")


class AdminInvitationItem(StrictInvitationAPIModel):
    """An invitation as admins see it.

    ``invited_by_user_id`` is the admin who created or last resent it, null
    once that account is deleted. ``expired`` says ``expires_at`` has passed:
    it can't be accepted, but it can be resent. ``last_sent_at`` is when
    Postmark accepted the email with the current link, null when the last
    send failed or wasn't tried; ``last_send_error`` then names why, as a
    short identifier such as ``not_configured``, ``timeout``, ``http_500``
    or ``postmark_406`` (an address Postmark suppresses).
    """

    id: UUID
    email: str
    user_type: Literal["author", "admin"]
    invited_by_user_id: UUID | None
    created_at: datetime
    expires_at: datetime
    expired: bool
    last_sent_at: datetime | None
    last_send_error: str | None

    @classmethod
    def from_read(cls, invitation: AdminInvitationRead) -> AdminInvitationItem:
        """Convert the service's read model; the type is validated as a literal."""
        return cls.model_validate(
            {
                "id": invitation.id,
                "email": invitation.email,
                "user_type": invitation.user_type.value,
                "invited_by_user_id": invitation.invited_by_user_id,
                "created_at": invitation.created_at,
                "expires_at": invitation.expires_at,
                "expired": invitation.expired,
                "last_sent_at": invitation.last_sent_at,
                "last_send_error": invitation.last_send_error,
            }
        )


class AdminInvitationResult(StrictInvitationAPIModel):
    """Result holding one invitation in ``item``."""

    item: AdminInvitationItem


class AdminInvitationPageResult(StrictInvitationAPIModel):
    """One page of open invitations, newest first."""

    items: list[AdminInvitationItem]
    offset: int
    limit: int
    has_more: bool

    @classmethod
    def from_page(cls, page: AdminInvitationPage) -> AdminInvitationPageResult:
        """Convert the service's page."""
        return cls(
            items=[AdminInvitationItem.from_read(item) for item in page.items],
            offset=page.offset,
            limit=page.limit,
            has_more=page.has_more,
        )


ResultT = TypeVar("ResultT")


class InvitationSuccessResponse(StrictInvitationAPIModel, Generic[ResultT]):
    """Success envelope: ``status`` "ok", a null ``message`` and the ``result``."""

    status: Literal["ok"] = "ok"
    message: None = None
    result: ResultT


class AdminInvitationResponse(InvitationSuccessResponse[AdminInvitationResult]):
    """Success response holding one invitation."""


class AdminInvitationPageResponse(InvitationSuccessResponse[AdminInvitationPageResult]):
    """Success response holding one page of open invitations."""
