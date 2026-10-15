"""Framework-independent data exchanged by v2 user-simulation layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import model_validator

from policyengine_api.query_parameters import CountryId, UserId
from policyengine_api.services.v2.associations.types import (
    AssociationDescription,
    AssociationName,
    StrictAssociationModel,
)
from policyengine_api.services.v2.legacy_refs.types import LegacyRecordId

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


class StrictUserSimulationInput(StrictAssociationModel):
    """Reject fields outside the reviewed user-simulation contract."""


class UserSimulationCreateFields(StrictUserSimulationInput):
    """Caller-supplied fields; Stage 12A accepts only v1 simulation references."""

    country_id: CountryId
    legacy_simulation_id: LegacyRecordId
    name: AssociationName | None = None
    description: AssociationDescription | None = None


class UserSimulationCreationInput(StrictUserSimulationInput):
    """Complete persisted association values, including the resolved owner."""

    country_id: CountryId
    user_id: UserId
    legacy_simulation_id: LegacyRecordId
    name: AssociationName | None = None
    description: str | None = None


class UserSimulationUpdateInput(StrictUserSimulationInput):
    """A partial update of a saved simulation; only supplied fields change.

    At least one field must be supplied. ``legacy_simulation_id`` repoints the
    saved simulation to another v1 simulation and cannot be cleared.
    """

    legacy_simulation_id: LegacyRecordId | None = None
    name: AssociationName | None = None
    description: AssociationDescription | None = None

    @model_validator(mode="after")
    def require_valid_supplied_field(self) -> UserSimulationUpdateInput:
        """Require a supplied field and reject a null ``legacy_simulation_id``."""
        supplied = self.model_fields_set.intersection(
            {"legacy_simulation_id", "name", "description"}
        )
        if not supplied:
            msg = (
                "At least one of legacy_simulation_id, name, or description must "
                "be supplied"
            )
            raise ValueError(msg)
        if "legacy_simulation_id" in supplied and self.legacy_simulation_id is None:
            msg = "legacy_simulation_id must not be null"
            raise ValueError(msg)
        return self


@dataclass(frozen=True)
class UserSimulationRead:
    """A stored user-simulation association as the service returns it to routes.

    Stage 12A saves only v1 simulations, so ``legacy_simulation_id`` names the
    simulation and ``simulation_id`` is a logical reference with no foreign key.
    """

    id: UUID
    country_id: str
    user_id: UUID
    simulation_id: UUID | None
    legacy_simulation_id: int | None
    name: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class UserSimulationPage:
    """One page of associations in creation order; ``has_more`` says if more follow."""

    items: tuple[UserSimulationRead, ...]
    offset: int
    limit: int
    has_more: bool
