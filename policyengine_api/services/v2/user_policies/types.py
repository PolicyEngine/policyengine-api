"""Framework-independent data exchanged by v2 user-policy layers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import Field, StringConstraints, model_validator

from policyengine_api.query_parameters import (
    CountryId,
    LegacyUserId,
    ResourceId,
    UserId,
)
from policyengine_api.services.v2.associations.types import (
    AssociationDescription,
    AssociationName,
    StrictAssociationModel,
)
from policyengine_api.services.v2.legacy_refs.types import LegacyRecordId

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

UserPolicyBaseline = Literal["current-law", "current-policy"]


class StrictAssociationInput(StrictAssociationModel):
    """Reject fields outside the reviewed association contract."""


class PolicyProvenance(StrictAssociationInput):
    """Where a v3 reform came from."""

    source: Literal["manual", "chat", "bill", "tool"]
    ref: Annotated[str, StringConstraints(max_length=2048)] | None = None
    confidence: Literal["exact", "approximated", "partial"] | None = None


class UserPolicyCreateFields(StrictAssociationInput):
    """Caller-supplied association fields; the owner comes from the session."""

    country_id: CountryId
    policy_id: ResourceId | None = None
    legacy_policy_id: LegacyRecordId | None = None
    name: AssociationName | None = None
    description: AssociationDescription | None = None
    baseline: UserPolicyBaseline | None = None
    provenance: PolicyProvenance | None = None

    @model_validator(mode="after")
    def require_policy_reference(self) -> UserPolicyCreateFields:
        """Require a v2 policy_id, a v1 legacy_policy_id, or both."""
        if self.policy_id is None and self.legacy_policy_id is None:
            msg = "At least one of legacy_policy_id or policy_id is required"
            raise ValueError(msg)
        return self


class UserPolicyCreationInput(StrictAssociationInput):
    """Complete persisted association values, including the resolved owner."""

    country_id: CountryId
    user_id: UserId
    policy_id: ResourceId | None = None
    # The Stage 10 mirror projects any committed v1 reform identifier.
    legacy_policy_id: Annotated[int, Field(ge=0)] | None = None
    name: AssociationName | None = None
    description: str | None = None
    baseline: UserPolicyBaseline | None = None
    provenance: PolicyProvenance | None = None

    @model_validator(mode="after")
    def require_policy_reference(self) -> UserPolicyCreationInput:
        """Require a v2 policy_id, a v1 legacy_policy_id, or both."""
        if self.policy_id is None and self.legacy_policy_id is None:
            msg = "At least one of legacy_policy_id or policy_id is required"
            raise ValueError(msg)
        return self


class UserPolicyUpdateInput(StrictAssociationInput):
    """A partial update of a saved policy; only supplied fields are changed.

    At least one field must be supplied. ``policy_id`` points the association at
    another v2 policy; supplied without ``legacy_policy_id``, it also clears the
    v1 reference, which no longer describes the saved policy. ``legacy_policy_id``
    alone points the association at another v1 policy and takes ``policy_id`` from
    that policy's v2 copy. Supplied together, both are stored, and ``policy_id``
    must be that v2 copy when the Stage 10 mirror made one. Neither reference can
    be set to null.
    """

    policy_id: ResourceId | None = None
    legacy_policy_id: LegacyRecordId | None = None
    name: AssociationName | None = None
    description: AssociationDescription | None = None
    baseline: UserPolicyBaseline | None = None
    provenance: PolicyProvenance | None = None

    @model_validator(mode="after")
    def require_supplied_field(self) -> UserPolicyUpdateInput:
        """Require a supplied field, and reject an explicit null policy reference."""
        supplied = self.model_fields_set.intersection(
            {
                "policy_id",
                "legacy_policy_id",
                "name",
                "description",
                "baseline",
                "provenance",
            }
        )
        if not supplied:
            msg = (
                "At least one of policy_id, legacy_policy_id, name, description, "
                "baseline, or provenance must be supplied"
            )
            raise ValueError(msg)
        for reference in ("policy_id", "legacy_policy_id"):
            if reference in supplied and getattr(self, reference) is None:
                msg = f"{reference} must not be null"
                raise ValueError(msg)
        return self

    @property
    def repoints(self) -> bool:
        """Whether the update changes which policy the association references."""
        return bool(
            self.model_fields_set.intersection({"policy_id", "legacy_policy_id"})
        )


@dataclass(frozen=True)
class UserPolicyReferences:
    """The v2 and v1 policy references a repointed association stores."""

    policy_id: UUID | None
    legacy_policy_id: int | None


class LegacyUserPolicySnapshot(StrictAssociationInput):
    """Detached complete committed v1 saved-policy row."""

    country_id: CountryId
    legacy_user_policy_id: Annotated[int, Field(ge=0)]
    reform_id: Annotated[int, Field(ge=0)]
    reform_label: Annotated[str, Field(max_length=255)] | None = None
    baseline_id: Annotated[int, Field(ge=0)]
    baseline_label: Annotated[str, Field(max_length=255)] | None = None
    user_id: LegacyUserId
    year: Annotated[str, Field(max_length=32)]
    geography: Annotated[str, Field(max_length=255)]
    dataset: Annotated[str, Field(max_length=255)] | None = None
    number_of_provisions: Annotated[int, Field(ge=0)]
    api_version: Annotated[str, Field(max_length=32)]
    added_date: int
    updated_date: int
    budgetary_impact: Annotated[str, Field(max_length=255)] | None = None
    type: Annotated[str, Field(max_length=255)] | None = None


class LegacyUserPolicyMappingAction(StrEnum):
    """What to do with a v1 saved-policy revision whose row is already mapped.

    STALE is older than the applied revision and is ignored, REPLAY repeats the
    applied revision, and UPDATE is the next revision, which is applied.
    """

    STALE = "stale"
    REPLAY = "replay"
    UPDATE = "update"


@dataclass(frozen=True)
class UserPolicyRead:
    """A stored user-policy association as the service returns it to routes."""

    id: UUID
    country_id: str
    user_id: UUID
    policy_id: UUID | None
    legacy_policy_id: int | None
    name: str | None
    description: str | None
    baseline: str | None
    provenance: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class UserPolicyPage:
    """One page of associations in creation order; ``has_more`` says if more follow."""

    items: tuple[UserPolicyRead, ...]
    offset: int
    limit: int
    has_more: bool


@dataclass(frozen=True)
class LegacyUserPolicyPersistenceResult:
    """Outcome of copying one v1 saved-policy revision into v2.

    Names the v2 association and policy, and whether this call created the
    association, renamed it, or created the v1-to-v2 mapping.
    """

    association_id: UUID
    policy_id: UUID
    association_created: bool
    association_updated: bool
    mapping_created: bool
