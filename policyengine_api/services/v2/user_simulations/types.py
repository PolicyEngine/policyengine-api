"""Framework-independent data exchanged by v2 user-simulation layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from policyengine_api.query_parameters import CountryId, UserId
from policyengine_api.services.v2.associations.types import (
    AssociationClientRef,
    AssociationName,
)
from policyengine_api.services.v2.legacy_refs.types import LegacyRecordId


class StrictUserSimulationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class UserSimulationCreateFields(StrictUserSimulationInput):
    """Caller-supplied fields; Stage 12A accepts only v1 simulation references."""

    country_id: CountryId
    legacy_simulation_id: LegacyRecordId
    name: AssociationName | None = None
    description: str | None = None
    client_ref: AssociationClientRef | None = None


class UserSimulationCreationInput(StrictUserSimulationInput):
    country_id: CountryId
    user_id: UserId
    legacy_simulation_id: LegacyRecordId
    name: AssociationName | None = None
    description: str | None = None
    client_ref: AssociationClientRef | None = None


class UserSimulationUpdateInput(StrictUserSimulationInput):
    legacy_simulation_id: LegacyRecordId | None = None
    name: AssociationName | None = None
    description: str | None = None

    @model_validator(mode="after")
    def require_valid_supplied_field(self) -> "UserSimulationUpdateInput":
        supplied = self.model_fields_set.intersection(
            {"legacy_simulation_id", "name", "description"}
        )
        if not supplied:
            raise ValueError(
                "At least one of legacy_simulation_id, name, or description must "
                "be supplied"
            )
        if "legacy_simulation_id" in supplied and self.legacy_simulation_id is None:
            raise ValueError("legacy_simulation_id must not be null")
        return self


class UserSimulationImportItem(StrictUserSimulationInput):
    """One browser-local saved simulation offered for idempotent import."""

    client_ref: AssociationClientRef
    legacy_simulation_id: LegacyRecordId
    name: AssociationName | None = None
    description: str | None = None


@dataclass(frozen=True)
class UserSimulationRead:
    id: UUID
    country_id: str
    user_id: UUID
    simulation_id: UUID | None
    legacy_simulation_id: int | None
    name: str | None
    description: str | None
    client_ref: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class UserSimulationPage:
    items: tuple[UserSimulationRead, ...]
    offset: int
    limit: int
    has_more: bool
