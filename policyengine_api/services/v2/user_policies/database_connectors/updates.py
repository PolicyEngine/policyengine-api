"""Database updates used by v2 user-policy operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.data.v2.models.base import utc_now
from policyengine_api.services.v2.user_policies.types import (
    USER_POLICY_REFERENCE_FIELDS,
)

if TYPE_CHECKING:
    from sqlmodel import Session

    from policyengine_api.data.v2.models import LegacyUserPolicyMapping, UserPolicy
    from policyengine_api.services.v2.user_policies.types import (
        LegacyUserPolicyRevision,
        UserPolicyReferences,
        UserPolicyUpdateInput,
    )


def update_user_policy(
    session: Session,
    association: UserPolicy,
    association_input: UserPolicyUpdateInput,
    *,
    references: UserPolicyReferences | None = None,
) -> UserPolicy:
    """Apply the supplied presentation fields, bump ``updated_at`` and return the row.

    With ``references``, also store both of its policy references; the service
    resolves them, so the request's own reference fields are never copied.
    """
    for field_name, value in association_input.model_dump(
        exclude_unset=True, exclude=set(USER_POLICY_REFERENCE_FIELDS)
    ).items():
        setattr(association, field_name, value)
    if references is not None:
        association.policy_id = references.policy_id
        association.legacy_policy_id = references.legacy_policy_id
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
    revision: LegacyUserPolicyRevision,
    update_name: bool,
) -> None:
    """Record a newly applied v1 revision on its mapping.

    With ``update_name``, also set the association's name to the v1 reform label.
    """
    if update_name:
        association.name = revision.reform_label
        association.updated_at = utc_now()
        session.add(association)
    mapping.fingerprint_sha256 = revision.fingerprint
    mapping.last_applied_source_revision = revision.source_revision
    mapping.updated_at = utc_now()
    session.add(mapping)
    session.flush()
