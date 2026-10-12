"""Database-independent validation for v2 account operations."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel, ValidationError

from policyengine_api.data.v2.models import User
from policyengine_api.services.v2.user_accounts.types import (
    ImportedRecord,
    ImportSkip,
    ImportSkipReason,
)


class AccountNotFoundError(LookupError):
    """Raised when the resolved account row is missing."""


class AccountIdentityDeletionError(RuntimeError):
    """Raised when account data was removed but the Auth0 user was not."""


ImportItemT = TypeVar("ImportItemT", bound=BaseModel)
LegacyItemT = TypeVar("LegacyItemT")


def require_account(user: User | None, *, user_id: UUID) -> User:
    if user is None:
        raise AccountNotFoundError(f"user {user_id} was not found")
    return user


def _client_ref(record: ImportedRecord) -> str | None:
    value = record.get("client_ref")
    return value if isinstance(value, str) else None


def partition_import_items(
    records: Sequence[ImportedRecord],
    item_type: type[ImportItemT],
) -> tuple[list[ImportItemT], list[ImportSkip]]:
    """Validate each record independently; invalid records are skipped."""

    valid: list[ImportItemT] = []
    skipped: list[ImportSkip] = []
    for record in records:
        try:
            valid.append(item_type.model_validate(record))
        except ValidationError:
            skipped.append(
                ImportSkip(
                    client_ref=_client_ref(record),
                    reason=ImportSkipReason.INVALID,
                )
            )
    return valid, skipped


def partition_known_legacy_items(
    items: Sequence[LegacyItemT],
    *,
    legacy_ids: Sequence[int],
    client_refs: Sequence[str],
    existing: Collection[int],
) -> tuple[list[LegacyItemT], list[ImportSkip]]:
    """Skip items whose v1 reference does not exist in the import country."""

    known: list[LegacyItemT] = []
    skipped: list[ImportSkip] = []
    for item, legacy_id, client_ref in zip(items, legacy_ids, client_refs, strict=True):
        if legacy_id in existing:
            known.append(item)
        else:
            skipped.append(
                ImportSkip(
                    client_ref=client_ref,
                    reason=ImportSkipReason.UNKNOWN_LEGACY_REFERENCE,
                )
            )
    return known, skipped
