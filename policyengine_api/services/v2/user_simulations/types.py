"""Framework-independent data exchanged by v2 user-simulation layers."""

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


class StrictUserSimulationInput(StrictAssociationModel):
    """Reject fields outside the reviewed user-simulation contract."""


def _require_simulation_reference(
    simulation_id: object | None, legacy_simulation_id: object | None
) -> None:
    if simulation_id is None and legacy_simulation_id is None:
        msg = "At least one of simulation_id or legacy_simulation_id is required"
        raise ValueError(msg)


class UserSimulationCreateFields(StrictUserSimulationInput):
    """Caller-supplied fields; the owner comes from the session.

    The saved simulation names a v2 simulation (``simulation_id``), a v1
    simulation (``legacy_simulation_id``), or both; each is checked before it
    is saved.
    """

    country_id: CountryId
    simulation_id: ResourceId | None = None
    legacy_simulation_id: LegacyRecordId | None = None
    name: AssociationName | None = None
    description: AssociationDescription | None = None

    @model_validator(mode="after")
    def require_simulation_reference(self) -> UserSimulationCreateFields:
        """Require a v2 simulation_id, a v1 legacy_simulation_id, or both."""
        _require_simulation_reference(self.simulation_id, self.legacy_simulation_id)
        return self


class UserSimulationCreationInput(StrictUserSimulationInput):
    """Complete persisted association values, including the resolved owner."""

    country_id: CountryId
    user_id: UserId
    simulation_id: ResourceId | None = None
    legacy_simulation_id: LegacyRecordId | None = None
    name: AssociationName | None = None
    description: str | None = None

    @model_validator(mode="after")
    def require_simulation_reference(self) -> UserSimulationCreationInput:
        """Require a v2 simulation_id, a v1 legacy_simulation_id, or both."""
        _require_simulation_reference(self.simulation_id, self.legacy_simulation_id)
        return self


class UserSimulationUpdateInput(StrictUserSimulationInput):
    """A partial update of a saved simulation; only supplied fields change.

    At least one field must be supplied. ``simulation_id`` repoints the saved
    simulation to a v2 simulation and ``legacy_simulation_id`` to another v1
    simulation; neither can be cleared.
    """

    simulation_id: ResourceId | None = None
    legacy_simulation_id: LegacyRecordId | None = None
    name: AssociationName | None = None
    description: AssociationDescription | None = None

    @model_validator(mode="after")
    def require_valid_supplied_field(self) -> UserSimulationUpdateInput:
        """Require a supplied field and reject a null simulation reference."""
        supplied = self.model_fields_set.intersection(
            {"simulation_id", "legacy_simulation_id", "name", "description"}
        )
        if not supplied:
            msg = (
                "At least one of simulation_id, legacy_simulation_id, name, or "
                "description must be supplied"
            )
            raise ValueError(msg)
        for reference in ("simulation_id", "legacy_simulation_id"):
            if reference in supplied and getattr(self, reference) is None:
                msg = f"{reference} must not be null"
                raise ValueError(msg)
        return self


@dataclass(frozen=True)
class UserSimulationRead:
    """A stored user-simulation association as the service returns it to routes.

    ``simulation_id`` names a v2 simulation, a logical reference with no
    foreign key, and ``legacy_simulation_id`` a v1 simulation.
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
class UserSimulationListing:
    """One page of a user's associations to read, optionally for one v1 simulation."""

    country_id: str
    user_id: UUID
    legacy_simulation_id: int | None
    offset: int
    limit: int


@dataclass(frozen=True)
class UserSimulationPage:
    """One page of associations in creation order; ``has_more`` says if more follow."""

    items: tuple[UserSimulationRead, ...]
    offset: int
    limit: int
    has_more: bool
