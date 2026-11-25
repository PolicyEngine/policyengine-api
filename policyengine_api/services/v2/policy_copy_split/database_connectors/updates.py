"""Database updates used by the policy copy split."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import update
from sqlmodel import col

from policyengine_api.data.v2.models import LegacyPolicyMapping, UserPolicy
from policyengine_api.data.v2.models.base import utc_now

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel import Session


def repoint_legacy_policy_mapping(
    session: Session, mapping_id: UUID, *, policy_id: UUID, dynamic_id: UUID
) -> None:
    """Point a legacy policy mapping at a policy and a dynamic."""
    session.execute(
        update(LegacyPolicyMapping)
        .where(col(LegacyPolicyMapping.id) == mapping_id)
        .values(policy_id=policy_id, dynamic_id=dynamic_id, updated_at=utc_now())
    )


def repoint_saved_policy(
    session: Session, saved_policy_id: UUID, *, policy_id: UUID
) -> None:
    """Point a saved policy at another policy; its name and description stay."""
    session.execute(
        update(UserPolicy)
        .where(col(UserPolicy.id) == saved_policy_id)
        .values(policy_id=policy_id, updated_at=utc_now())
    )
