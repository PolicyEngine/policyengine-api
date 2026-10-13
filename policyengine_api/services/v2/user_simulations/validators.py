"""Database-independent validation for v2 user-simulation operations."""

from __future__ import annotations

from uuid import UUID

from policyengine_api.data.v2.models import UserSimulationAssociation
from policyengine_api.services.v2.associations.validators import (
    AssociationNotFoundError,
)


class UserSimulationNotFoundError(AssociationNotFoundError):
    """Raised when an association is absent for the caller and country."""


def require_user_simulation(
    association: UserSimulationAssociation | None,
    *,
    association_id: UUID,
) -> UserSimulationAssociation:
    if association is None:
        raise UserSimulationNotFoundError(
            f"user-simulation association {association_id} was not found"
        )
    return association
