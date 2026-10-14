"""Strict HTTP request models for the account resource."""

from policyengine_api.services.v2.user_accounts.types import AccountUpdateInput


class AccountPatchRequest(AccountUpdateInput):
    """Explicitly supplied account presentation fields."""
