"""Database-independent validation for v2 account operations."""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Iterable, Sequence
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


class AccountDeletionUnavailableError(RuntimeError):
    """Raised before any data is deleted when Auth0 deletion cannot run."""


ImportItemT = TypeVar("ImportItemT", bound=BaseModel)
LegacyItemT = TypeVar("LegacyItemT")


def require_account(user: User | None, *, user_id: UUID) -> User:
    if user is None:
        raise AccountNotFoundError(f"user {user_id} was not found")
    return user


def _client_ref(record: ImportedRecord) -> str | None:
    value = record.get("client_ref")
    return value if isinstance(value, str) else None


def duplicated_client_refs(
    record_groups: Iterable[Sequence[ImportedRecord]],
) -> frozenset[str]:
    """Return the client_refs carried by more than one record of one request.

    ``id_map`` is keyed by client_ref alone, so it cannot tell records that
    share one apart, and a client removes its local item once the client_ref
    comes back in ``id_map``. Counting across every kind keeps a stored record
    and a skipped one from sharing a client_ref in one response.
    """

    occurrences = Counter(
        _client_ref(record) for records in record_groups for record in records
    )
    return frozenset(
        client_ref
        for client_ref, count in occurrences.items()
        if client_ref is not None and count > 1
    )


def partition_import_items(
    records: Sequence[ImportedRecord],
    item_type: type[ImportItemT],
    *,
    duplicates: Collection[str],
) -> tuple[list[ImportItemT], list[ImportSkip]]:
    """Validate each record independently; invalid records are skipped.

    Every record whose client_ref is in ``duplicates`` is skipped as invalid
    without validation, so none of the records sharing it is stored.
    """

    valid: list[ImportItemT] = []
    skipped: list[ImportSkip] = []
    for record in records:
        client_ref = _client_ref(record)
        if client_ref is not None and client_ref in duplicates:
            skipped.append(
                ImportSkip(client_ref=client_ref, reason=ImportSkipReason.INVALID)
            )
            continue
        try:
            valid.append(item_type.model_validate(record))
        except ValidationError:
            skipped.append(
                ImportSkip(
                    client_ref=client_ref,
                    reason=ImportSkipReason.INVALID,
                )
            )
    return valid, skipped


def client_ref_conflict_skips(client_refs: Sequence[str]) -> list[ImportSkip]:
    """Report client_refs the owner already uses in another country."""

    return [
        ImportSkip(client_ref=client_ref, reason=ImportSkipReason.CLIENT_REF_CONFLICT)
        for client_ref in client_refs
    ]


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
