"""Database-independent validation for v2 user-report operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.associations.validators import (
    AssociationLinkNotFoundError,
    AssociationNotFoundError,
)

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.data.v2.models import UserReportAssociation


class UserReportNotFoundError(AssociationNotFoundError):
    """Raised when an association is absent for the caller and country."""


def require_user_report(
    association: UserReportAssociation | None,
    *,
    association_id: UUID,
) -> UserReportAssociation:
    """Return the association, or raise UserReportNotFoundError if it is None."""
    if association is None:
        msg = f"user-report association {association_id} was not found"
        raise UserReportNotFoundError(msg)
    return association


def require_owned_user_policy(*, owned: bool, user_policy_id: UUID) -> None:
    """Raise AssociationLinkNotFoundError unless a linked saved policy is ``owned``.

    ``owned`` says whether the report's owner has that saved policy in the
    report's country.
    """
    if not owned:
        msg = (
            f"user-policy association {user_policy_id} was not found for this "
            "user and country"
        )
        raise AssociationLinkNotFoundError(msg)
