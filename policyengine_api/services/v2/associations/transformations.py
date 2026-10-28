"""Pure transformations shared by the saved-record association services."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.associations.types import RecordReferences

if TYPE_CHECKING:
    from uuid import UUID


def repointed_references(
    stored: RecordReferences, *, v2_id: UUID | None, legacy_id: int | None
) -> RecordReferences:
    """Return the references an association holds once an update applies.

    ``v2_id`` and ``legacy_id`` are the update's; None leaves the stored one,
    since neither reference can be cleared.
    """
    return RecordReferences(
        v2_id=stored.v2_id if v2_id is None else v2_id,
        legacy_id=stored.legacy_id if legacy_id is None else legacy_id,
    )
