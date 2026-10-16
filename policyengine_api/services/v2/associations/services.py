"""Operations shared by the four user-owned association services."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.associations.validators import (
    require_legacy_reference_checker,
)

if TYPE_CHECKING:
    from policyengine_api.services.v2.associations.types import LegacyReferenceChecker
    from policyengine_api.services.v2.legacy_refs.types import LegacyRecordKind


def require_legacy_reference(
    legacy_references: LegacyReferenceChecker | None,
    kind: LegacyRecordKind,
    *,
    country_id: str,
    legacy_id: int,
) -> None:
    """Check one v1 reference before the caller opens its v2 transaction."""
    require_legacy_reference_checker(legacy_references).require_existing(
        country_id=country_id,
        requested={kind: (legacy_id,)},
    )
