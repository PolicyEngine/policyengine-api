"""Database-independent validation for users' saved dynamics."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.associations.validators import (
    AssociationNotFoundError,
    AssociationReferenceConflictError,
)

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.data.v2.models import Dynamic, UserDynamic


class UserDynamicNotFoundError(AssociationNotFoundError):
    """Raised when a saved dynamic is absent for the caller and country."""


class AssociationDynamicNotFoundError(LookupError):
    """Raised when a saved dynamic names an unknown dynamic."""


class AssociationDynamicCountryConflictError(AssociationReferenceConflictError):
    """Raised when a saved dynamic names a dynamic stored in another country."""


def require_user_dynamic(
    saved_dynamic: UserDynamic | None, *, association_id: UUID
) -> UserDynamic:
    """Return the saved dynamic, or raise UserDynamicNotFoundError if it is None."""
    if saved_dynamic is None:
        msg = f"saved dynamic {association_id} was not found"
        raise UserDynamicNotFoundError(msg)
    return saved_dynamic


def validate_association_dynamic(
    *,
    country_id: str,
    dynamic_id: UUID,
    dynamic: Dynamic | None,
) -> None:
    """Check that a named dynamic exists and is stored in the saved dynamic's country.

    Raise AssociationDynamicNotFoundError or AssociationDynamicCountryConflictError.
    """
    if dynamic is None:
        msg = f"dynamic {dynamic_id} was not found"
        raise AssociationDynamicNotFoundError(msg)
    if dynamic.country_id != country_id:
        msg = "A saved dynamic's country_id must match the dynamic's country"
        raise AssociationDynamicCountryConflictError(msg)
