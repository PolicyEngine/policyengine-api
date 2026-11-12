"""Database-independent validation for v2 user-simulation operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.associations.validators import (
    AssociationNotFoundError,
)

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.data.v2.models import UserSimulationAssociation


class UserSimulationNotFoundError(AssociationNotFoundError):
    """Raised when an association is absent for the caller and country."""


class AssociationSimulationNotFoundError(LookupError):
    """A saved simulation names a detailed-save simulation the country lacks."""


# The foreign key from saved simulations to simulations (``RESTRICT``).
SAVED_SIMULATION_FOREIGN_KEY = (
    "fk_user_simulation_associations_simulation_id_simulations"
)


def simulation_not_found(
    *, simulation_id: UUID, country_id: str
) -> AssociationSimulationNotFoundError:
    """Return the error for a detailed-save simulation the country does not have."""
    return AssociationSimulationNotFoundError(
        f"Simulation {simulation_id} was not found in country {country_id!r}"
    )


def require_stored_simulation(
    *, stored: bool, simulation_id: UUID, country_id: str
) -> None:
    """Raise AssociationSimulationNotFoundError unless the simulation is ``stored``."""
    if not stored:
        raise simulation_not_found(simulation_id=simulation_id, country_id=country_id)


def require_user_simulation(
    association: UserSimulationAssociation | None,
    *,
    association_id: UUID,
) -> UserSimulationAssociation:
    """Return the association, or raise UserSimulationNotFoundError if it is None."""
    if association is None:
        msg = f"user-simulation association {association_id} was not found"
        raise UserSimulationNotFoundError(msg)
    return association
