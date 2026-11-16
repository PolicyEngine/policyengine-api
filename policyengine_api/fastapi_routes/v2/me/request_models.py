"""Strict HTTP request models for the account resource."""

from pydantic import BaseModel, ConfigDict

from policyengine_api.services.v2.user_accounts.types import AccountUpdateInput
from policyengine_api.services.v2.user_invitations.types import InvitationToken


class AccountPatchRequest(AccountUpdateInput):
    """Explicitly supplied account presentation fields."""


class InvitationAcceptRequest(BaseModel):
    """The token from an invitation's link, from its ``#token=`` fragment."""

    model_config = ConfigDict(extra="forbid")

    token: InvitationToken
