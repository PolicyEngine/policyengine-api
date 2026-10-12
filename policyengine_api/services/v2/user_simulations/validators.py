"""Database-independent validation for v2 user-simulation operations."""

from __future__ import annotations

from uuid import UUID

from policyengine_api.data.v2.models import UserSimulationAssociation
from policyengine_api.services.v2.associations.validators import (
    AssociationNotFoundError,
)


class UserSimulationNotFoundError(AssociationNotFoundError):
    """Raised when an association is absent for the caller and country."""


class UserSimulationImportIntegrityError(RuntimeError):
    """Raised when an imported client_ref resolves to no stored association."""


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


def require_imported_user_simulation(association_id: UUID | None) -> UUID:
    if association_id is None:
        raise UserSimulationImportIntegrityError(
            "imported user-simulation client_ref did not resolve to a stored row"
        )
    return association_id
