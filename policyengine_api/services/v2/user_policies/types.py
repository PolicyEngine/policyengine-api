"""Framework-independent data exchanged by v2 user-policy layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

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
    def require_policy_reference(self) -> "UserPolicyCreateFields":
        if self.policy_id is None and self.legacy_policy_id is None:
            raise ValueError(
                "At least one of legacy_policy_id or policy_id is required"
            )
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
    def require_policy_reference(self) -> "UserPolicyCreationInput":
        if self.policy_id is None and self.legacy_policy_id is None:
            raise ValueError(
                "At least one of legacy_policy_id or policy_id is required"
            )
        return self


class UserPolicyUpdateInput(StrictAssociationInput):
    legacy_policy_id: LegacyRecordId | None = None
    name: AssociationName | None = None
    description: AssociationDescription | None = None
    baseline: UserPolicyBaseline | None = None
    provenance: PolicyProvenance | None = None

    @model_validator(mode="after")
    def require_supplied_field(self) -> "UserPolicyUpdateInput":
        supplied = self.model_fields_set.intersection(
            {"legacy_policy_id", "name", "description", "baseline", "provenance"}
        )
        if not supplied:
            raise ValueError(
                "At least one of legacy_policy_id, name, description, baseline, "
                "or provenance must be supplied"
            )
        if "legacy_policy_id" in supplied and self.legacy_policy_id is None:
            raise ValueError("legacy_policy_id must not be null")
        return self


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
    STALE = "stale"
    REPLAY = "replay"
    UPDATE = "update"


@dataclass(frozen=True)
class UserPolicyRead:
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
    items: tuple[UserPolicyRead, ...]
    offset: int
    limit: int
    has_more: bool


@dataclass(frozen=True)
class LegacyUserPolicyPersistenceResult:
    association_id: UUID
    policy_id: UUID
    association_created: bool
    association_updated: bool
    mapping_created: bool
