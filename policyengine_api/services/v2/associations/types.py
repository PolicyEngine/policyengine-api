"""Framework-independent field types shared by user association resources."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, StringConstraints

from policyengine_api.data.v2.models.associations import (
    ASSOCIATION_CLIENT_REF_MAX_LENGTH,
)
from policyengine_api.services.v2.legacy_refs.types import LegacyRecordKind


AssociationName = Annotated[str, StringConstraints(max_length=255)]
AssociationClientRef = Annotated[
    str,
    StringConstraints(min_length=1, max_length=ASSOCIATION_CLIENT_REF_MAX_LENGTH),
]


class StrictAssociationModel(BaseModel):
    """Reject fields outside a reviewed association contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class LegacyReferenceChecker(Protocol):
    """Read-only v1 existence checks performed before a v2 transaction."""

    def existing_ids(
        self,
        *,
        country_id: str,
        requested: Mapping[LegacyRecordKind, Collection[int]],
    ) -> dict[LegacyRecordKind, frozenset[int]]: ...

    def require_existing(
        self,
        *,
        country_id: str,
        requested: Mapping[LegacyRecordKind, Collection[int]],
    ) -> None: ...
