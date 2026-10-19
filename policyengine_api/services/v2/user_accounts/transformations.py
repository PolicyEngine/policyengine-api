"""Pure representation transformations for v2 account operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from policyengine_api.services.v2.user_accounts.types import (
    AccountRead,
    AccountUpdateInput,
)

if TYPE_CHECKING:
    from policyengine_api.data.v2.models import User


def account_read(user: User, *, email: str | None) -> AccountRead:
    """Convert a user row to the account read model, preferring the identity's email."""
    return AccountRead(
        id=user.id,
        user_type=user.user_type,
        primary_country=user.primary_country,
        first_name=user.first_name,
        last_name=user.last_name,
        email=email if email is not None else user.email,
        created_at=user.created_at,
    )


def account_update_values(account_input: AccountUpdateInput) -> dict[str, Any]:
    """Return only the fields the caller supplied, including explicit nulls."""
    return account_input.model_dump(exclude_unset=True)
