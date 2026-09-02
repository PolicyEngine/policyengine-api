"""Framework-independent data exchanged by v2 user-policy layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from policyengine_api.query_parameters import (
    CountryId,
    LegacyUserId,
    ResourceId,
    UserId,
)


class StrictAssociationInput(BaseModel):
    """Reject fields outside the reviewed association contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class UserPolicyCreationInput(StrictAssociationInput):
    country_id: CountryId
    user_id: UserId
    policy_id: ResourceId
    name: Annotated[str, StringConstraints(max_length=255)] | None = None
    description: str | None = None


class UserPolicyUpdateInput(StrictAssociationInput):
    name: Annotated[str, StringConstraints(max_length=255)] | None = None
    description: str | None = None

    @model_validator(mode="after")
    def require_supplied_field(self) -> "UserPolicyUpdateInput":
        if not self.model_fields_set.intersection({"name", "description"}):
            raise ValueError("At least one of name or description must be supplied")
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
    policy_id: UUID
    name: str | None
    description: str | None
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
