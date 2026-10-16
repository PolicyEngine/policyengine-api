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


def require_user_simulation(
    association: UserSimulationAssociation | None,
    *,
    association_id: UUID,
) -> UserSimulationAssociation:
    """Return the association, or raise UserSimulationNotFoundError if it is None."""
    if association is None:
        raise UserSimulationNotFoundError(
            f"user-simulation association {association_id} was not found"
        )
    return association
