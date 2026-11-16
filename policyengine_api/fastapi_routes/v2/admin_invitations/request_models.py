"""Strict HTTP request models for admins' email invitation routes."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from policyengine_api.services.v2.user_invitations.types import (
    InvitationEmailAddress,
)


class InvitationCreateRequest(BaseModel):
    """The address an admin invites, and the type the invitation grants.

    ``email`` is stripped of surrounding whitespace and must be one address:
    an @ with text on both sides and no whitespace, < or >.
    """

    model_config = ConfigDict(extra="forbid")

    email: InvitationEmailAddress
    user_type: Literal["author", "admin"]
