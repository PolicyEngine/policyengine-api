"""Transactional persistence for mutable user-policy associations."""

from __future__ import annotations

from uuid import UUID

from sqlmodel import Session, select

from policyengine_api.data.v2.models import Policy, UserPolicy
from policyengine_api.data.v2.models.base import utc_now
from policyengine_api.data.v2.user_policies.query import (
    UserPolicyRead,
    association_read,
    get_user_policy_row,
)
from policyengine_api.data.v2.user_policies.schemas import (
    UserPolicyCreateCommand,
    UserPolicyPatchCommand,
)


class AssociationPolicyNotFoundError(LookupError):
    """Raised when an association references an unknown policy UUID."""


class AssociationCountryConflictError(ValueError):
    """Raised when an association and its referenced policy differ by country."""


def create_user_policy(
    session: Session,
    command: UserPolicyCreateCommand,
) -> UserPolicyRead:
    """Create one independently identified association after policy validation."""

    policy = session.exec(
        select(Policy).where(Policy.id == command.policy_id)
    ).one_or_none()
    if policy is None:
        raise AssociationPolicyNotFoundError(
            f"policy {command.policy_id} was not found"
        )
    if policy.country_id != command.country_id:
        raise AssociationCountryConflictError(
            "Association country_id must match the referenced policy"
        )
    association = UserPolicy(**command.model_dump())
    session.add(association)
    session.flush()
    session.refresh(association)
    return association_read(association)


def patch_user_policy(
    session: Session,
    *,
    country_id: str,
    association_id: UUID,
    command: UserPolicyPatchCommand,
) -> UserPolicyRead:
    """Change only explicitly supplied presentation fields."""

    association = get_user_policy_row(
        session,
        country_id=country_id,
        association_id=association_id,
    )
    changes = command.model_dump(exclude_unset=True)
    for field_name, value in changes.items():
        setattr(association, field_name, value)
    association.updated_at = utc_now()
    session.add(association)
    session.flush()
    session.refresh(association)
    return association_read(association)


def delete_user_policy(
    session: Session,
    *,
    country_id: str,
    association_id: UUID,
) -> None:
    """Delete one association; database cascades remove only its legacy mapping."""

    association = get_user_policy_row(
        session,
        country_id=country_id,
        association_id=association_id,
    )
    session.delete(association)
    session.flush()
