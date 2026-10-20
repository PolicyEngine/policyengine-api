"""Bad fixture: a runtime read of a table the runtime role has no grant on.

This is the mistake behind issue #3977. ``POST /v2/user-policies`` started
reading ``legacy_policy_mappings`` to fill ``policy_id``, but no one granted the
runtime role SELECT on that table, so every reform save returned 503.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import LegacyPolicyMapping, UserPolicy

if TYPE_CHECKING:
    from uuid import UUID


def read_mirrored_policy_ids(
    session: Session, *, country_id: str, legacy_policy_ids: list[int]
) -> dict[int, UUID]:
    """Return v2 policy UUIDs for v1 policies the Stage 10 mirror copied."""
    rows = session.exec(
        select(
            LegacyPolicyMapping.legacy_policy_id, LegacyPolicyMapping.policy_id
        ).where(
            LegacyPolicyMapping.country_id == country_id,
            col(LegacyPolicyMapping.legacy_policy_id).in_(legacy_policy_ids),
        )
    ).all()
    return {int(legacy_policy_id): policy_id for legacy_policy_id, policy_id in rows}


def read_user_policy_row(session: Session, association_id: UUID) -> UserPolicy | None:
    """Return the saved policy with this id, or None."""
    return session.get(UserPolicy, association_id)
