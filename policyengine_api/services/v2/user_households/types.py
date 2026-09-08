"""Framework-independent data exchanged by v2 user-household layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from policyengine_api.query_parameters import CountryId, ResourceId, UserId


AssociationName = Annotated[str, StringConstraints(max_length=255)]


class StrictUserHouseholdInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class UserHouseholdCreationInput(StrictUserHouseholdInput):
    country_id: CountryId
    user_id: UserId
    household_id: ResourceId
    name: AssociationName | None = None
    description: str | None = None


class UserHouseholdUpdateInput(StrictUserHouseholdInput):
    household_id: ResourceId | None = None
    name: AssociationName | None = None
    description: str | None = None

    @model_validator(mode="after")
    def require_valid_supplied_field(self) -> "UserHouseholdUpdateInput":
        mutable_fields = {"household_id", "name", "description"}
        supplied = self.model_fields_set.intersection(mutable_fields)
        if not supplied:
            raise ValueError(
                "At least one of household_id, name, or description must be supplied"
            )
        if "household_id" in supplied and self.household_id is None:
            raise ValueError("household_id must not be null")
        return self


@dataclass(frozen=True)
class UserHouseholdRead:
    id: UUID
    country_id: str
    user_id: UUID
    household_id: UUID
    name: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class UserHouseholdPage:
    items: tuple[UserHouseholdRead, ...]
    offset: int
    limit: int
    has_more: bool
