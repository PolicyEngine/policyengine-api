"""Database-independent validation of v1 artifact references."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection

    from policyengine_api.services.v2.legacy_refs.types import LegacyRecordKind


class LegacyReferenceNotFoundError(LookupError):
    """Raised when a referenced v1 artifact does not exist in its country."""


def require_legacy_references(
    kind: LegacyRecordKind,
    *,
    country_id: str,
    requested: Collection[int],
    existing: Collection[int],
) -> None:
    missing = sorted(set(requested) - set(existing))
    if missing:
        rendered = ", ".join(str(legacy_id) for legacy_id in missing)
        raise LegacyReferenceNotFoundError(
            f"v1 {kind.value} {rendered} was not found for country {country_id}"
        )
