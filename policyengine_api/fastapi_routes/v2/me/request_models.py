"""Strict HTTP request models for the signed-in account resource."""

from policyengine_api.services.v2.user_accounts.types import (
    AccountImportInput,
    AccountUpdateInput,
)


class AccountPatchRequest(AccountUpdateInput):
    """Explicitly supplied account presentation fields."""


class AccountImportRequest(AccountImportInput):
    """Browser-local records offered for idempotent import (at most 500)."""
