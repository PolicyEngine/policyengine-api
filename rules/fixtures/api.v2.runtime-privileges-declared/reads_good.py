"""Good fixture: a runtime read of only the tables the runtime role is granted.

The user-policy lookup reads ``user_policy_associations``, which the runtime
role holds SELECT on, and nothing else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.data.v2.models import UserPolicy

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.data.v2.models import LegacyPolicyMapping


def read_user_policy_row(session: Session, association_id: UUID) -> UserPolicy | None:
    """Return the saved policy with this id, or None."""
    return session.get(UserPolicy, association_id)


def describe_mapping(mapping: LegacyPolicyMapping) -> str:
    """Name a mapping the caller already holds; only its annotation uses the model."""
    return f"{mapping.country_id}:{mapping.legacy_policy_id}"
