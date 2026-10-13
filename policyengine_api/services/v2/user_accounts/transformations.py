"""Pure representation transformations for v2 account operations."""

from __future__ import annotations

from typing import Any

from policyengine_api.data.v2.models import User
from policyengine_api.services.v2.identity.types import ResolvedUser
from policyengine_api.services.v2.user_accounts.types import (
    AccountRead,
    AccountUpdateInput,
)


def account_read(user: User, *, owner: ResolvedUser) -> AccountRead:
    return AccountRead(
        id=user.id,
        primary_country=user.primary_country,
        first_name=user.first_name,
        last_name=user.last_name,
        email=owner.email if owner.email is not None else user.email,
        created_at=user.created_at,
        account_created=owner.provisioned,
    )


def account_update_values(account_input: AccountUpdateInput) -> dict[str, Any]:
    return account_input.model_dump(exclude_unset=True)
