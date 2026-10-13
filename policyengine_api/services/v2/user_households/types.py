"""Framework-independent data exchanged by v2 user-household layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import model_validator

from policyengine_api.query_parameters import CountryId, ResourceId, UserId
from policyengine_api.services.v2.associations.types import (
    AssociationDescription,
    AssociationName,
    StrictAssociationModel,
)
from policyengine_api.services.v2.legacy_refs.types import LegacyRecordId

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


class StrictUserHouseholdInput(StrictAssociationModel):
    """Reject fields outside the reviewed user-household contract."""


class UserHouseholdCreateFields(StrictUserHouseholdInput):
    """Caller-supplied association fields; the owner comes from the session."""

    country_id: CountryId
    household_id: ResourceId | None = None
    legacy_household_id: LegacyRecordId | None = None
    name: AssociationName | None = None
    description: AssociationDescription | None = None

    @model_validator(mode="after")
    def require_household_reference(self) -> UserHouseholdCreateFields:
        if self.household_id is None and self.legacy_household_id is None:
            raise ValueError(
                "At least one of legacy_household_id or household_id is required"
            )
        return self


class UserHouseholdCreationInput(StrictUserHouseholdInput):
    """Complete persisted association values, including the resolved owner."""

    country_id: CountryId
    user_id: UserId
    household_id: ResourceId | None = None
    legacy_household_id: LegacyRecordId | None = None
    name: AssociationName | None = None
    description: str | None = None

    @model_validator(mode="after")
    def require_household_reference(self) -> UserHouseholdCreationInput:
        if self.household_id is None and self.legacy_household_id is None:
            raise ValueError(
                "At least one of legacy_household_id or household_id is required"
            )
        return self


class UserHouseholdUpdateInput(StrictUserHouseholdInput):
    legacy_household_id: LegacyRecordId | None = None
    name: AssociationName | None = None
    description: AssociationDescription | None = None

    @model_validator(mode="after")
    def require_valid_supplied_field(self) -> UserHouseholdUpdateInput:
        mutable_fields = {"legacy_household_id", "name", "description"}
        supplied = self.model_fields_set.intersection(mutable_fields)
        if not supplied:
            raise ValueError(
                "At least one of legacy_household_id, name, or description must be "
                "supplied"
            )
        if "legacy_household_id" in supplied and self.legacy_household_id is None:
            raise ValueError("legacy_household_id must not be null")
        return self


@dataclass(frozen=True)
class UserHouseholdRead:
    """A stored user-household association as the service returns it to routes."""

    id: UUID
    country_id: str
    user_id: UUID
    household_id: UUID | None
    legacy_household_id: int | None
    name: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class UserHouseholdPage:
    """One page of associations in creation order; ``has_more`` says if more follow."""

    items: tuple[UserHouseholdRead, ...]
    offset: int
    limit: int
    has_more: bool
