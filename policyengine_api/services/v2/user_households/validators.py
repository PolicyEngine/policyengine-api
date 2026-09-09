"""Database-independent validation for v2 user-household operations."""

from __future__ import annotations

from uuid import UUID

from policyengine_api.data.v2.models import Household, User, UserHouseholdAssociation
from policyengine_api.services.v2.user_households.types import (
    UserHouseholdCreationInput,
)


class UserHouseholdNotFoundError(LookupError):
    """Raised when an association is absent from the selected country."""


class AssociationHouseholdNotFoundError(LookupError):
    """Raised when an association references an unknown household UUID."""


class AssociationUserNotFoundError(LookupError):
    """Raised when an association references an unknown v2 user UUID."""


class AssociationCountryConflictError(ValueError):
    """Raised when an association and household have different countries."""


def require_user_household(
    association: UserHouseholdAssociation | None,
    *,
    association_id: UUID,
) -> UserHouseholdAssociation:
    if association is None:
        raise UserHouseholdNotFoundError(
            f"user-household association {association_id} was not found"
        )
    return association


def validate_association_creation(
    association_input: UserHouseholdCreationInput,
    *,
    user: User | None,
    household: Household | None,
) -> None:
    if user is None:
        raise AssociationUserNotFoundError(
            f"user {association_input.user_id} was not found"
        )
    validate_association_household(
        country_id=association_input.country_id,
        household_id=association_input.household_id,
        household=household,
    )


def validate_association_household(
    *,
    country_id: str,
    household_id: UUID,
    household: Household | None,
) -> None:
    if household is None:
        raise AssociationHouseholdNotFoundError(
            f"household {household_id} was not found"
        )
    if household.country_id != country_id:
        raise AssociationCountryConflictError(
            "Association country_id must match the referenced household"
        )
