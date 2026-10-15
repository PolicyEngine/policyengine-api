"""Database updates used by v2 user-policy operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.data.v2.models.base import utc_now

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.data.v2.models import LegacyUserPolicyMapping, UserPolicy
    from policyengine_api.services.v2.user_policies.types import UserPolicyUpdateInput


def update_user_policy(
    session: Session,
    association: UserPolicy,
    association_input: UserPolicyUpdateInput,
    *,
    repointed_policy_id: UUID | None = None,
    repoint: bool = False,
) -> UserPolicy:
    """Apply the supplied fields, bump ``updated_at`` and return the row.

    With ``repoint``, also set ``policy_id`` to ``repointed_policy_id``.
    """
    for field_name, value in association_input.model_dump(exclude_unset=True).items():
        setattr(association, field_name, value)
    if repoint:
        association.policy_id = repointed_policy_id
    association.updated_at = utc_now()
    session.add(association)
    session.flush()
    session.refresh(association)
    return association


def update_legacy_user_policy_state(
    session: Session,
    *,
    association: UserPolicy,
    mapping: LegacyUserPolicyMapping,
    reform_label: str | None,
    update_name: bool,
    fingerprint: str,
    source_revision: int,
) -> None:
    """Record a newly applied v1 revision on its mapping.

    With ``update_name``, also set the association's name to the v1 reform label.
    """
    if update_name:
        association.name = reform_label
        association.updated_at = utc_now()
        session.add(association)
    mapping.fingerprint_sha256 = fingerprint
    mapping.last_applied_source_revision = source_revision
    mapping.updated_at = utc_now()
    session.add(mapping)
    session.flush()
