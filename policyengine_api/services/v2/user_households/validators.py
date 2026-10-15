"""Database-independent validation for v2 user-household operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.associations.validators import (
    AssociationNotFoundError,
    AssociationReferenceConflictError,
)

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.data.v2.models import Household, UserHouseholdAssociation


class UserHouseholdNotFoundError(AssociationNotFoundError):
    """Raised when an association is absent for the caller and country."""


class AssociationHouseholdNotFoundError(LookupError):
    """Raised when an association references an unknown household UUID."""


class AssociationUserNotFoundError(LookupError):
    """Raised when an association references an unknown v2 user UUID."""


class AssociationCountryConflictError(AssociationReferenceConflictError):
    """Raised when an association and household have different countries."""


def require_user_household(
    association: UserHouseholdAssociation | None,
    *,
    association_id: UUID,
) -> UserHouseholdAssociation:
    """Return the association, or raise UserHouseholdNotFoundError if it is None."""
    if association is None:
        raise UserHouseholdNotFoundError(
            f"user-household association {association_id} was not found"
        )
    return association


def validate_association_household(
    *,
    country_id: str,
    household_id: UUID,
    household: Household | None,
) -> None:
    """Check that a referenced household exists and is in the association's country.

    Raise AssociationHouseholdNotFoundError or AssociationCountryConflictError.
    """
    if household is None:
        raise AssociationHouseholdNotFoundError(
            f"household {household_id} was not found"
        )
    if household.country_id != country_id:
        raise AssociationCountryConflictError(
            "Association country_id must match the referenced household"
        )


def resolve_association_household_id(
    *,
    requested_household_id: UUID | None,
    mapped_household_id: UUID | None,
) -> UUID | None:
    """Combine an explicit v2 reference with the v1 mapping, if both exist."""
    if (
        requested_household_id is not None
        and mapped_household_id is not None
        and requested_household_id != mapped_household_id
    ):
        raise AssociationReferenceConflictError(
            "household_id does not match the household copied from legacy_household_id"
        )
    return (
        requested_household_id
        if requested_household_id is not None
        else mapped_household_id
    )
