"""Database-independent validation for v2 user-report operations."""

from __future__ import annotations

from uuid import UUID

from policyengine_api.data.v2.models import UserReportAssociation
from policyengine_api.services.v2.associations.validators import (
    AssociationLinkNotFoundError,
    AssociationNotFoundError,
)


class UserReportNotFoundError(AssociationNotFoundError):
    """Raised when an association is absent for the caller and country."""


def require_user_report(
    association: UserReportAssociation | None,
    *,
    association_id: UUID,
) -> UserReportAssociation:
    if association is None:
        raise UserReportNotFoundError(
            f"user-report association {association_id} was not found"
        )
    return association


def require_owned_user_policy(owned: bool, *, user_policy_id: UUID) -> None:
    if not owned:
        raise AssociationLinkNotFoundError(
            f"user-policy association {user_policy_id} was not found for this "
            "user and country"
        )
