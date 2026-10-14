"""Database inserts used by v2 user-policy operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col

from policyengine_api.data.v2.models import (
    LegacyUserMapping,
    LegacyUserPolicyMapping,
    User,
    UserPolicy,
)

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.services.v2.user_policies.types import (
        LegacyUserPolicyRevision,
        UserPolicyCreationInput,
    )


def create_user_policy(
    session: Session, association_input: UserPolicyCreationInput
) -> UserPolicy:
    """Insert an association and return it with its database-generated fields loaded."""
    association = UserPolicy(**association_input.model_dump())
    session.add(association)
    session.flush()
    session.refresh(association)
    return association


def create_transition_user(session: Session, *, primary_country: str) -> User:
    """Insert a v2 user to stand in for a v1 user that has no v2 user yet."""
    user = User(primary_country=primary_country)
    session.add(user)
    session.flush()
    return user


def create_legacy_user_mapping(
    session: Session, *, legacy_user_id: str, user_id: UUID
) -> UUID | None:
    """Map a v1 user id to a v2 user.

    Return the v2 user id, or None when the v1 id is already mapped (for example,
    a concurrent copy won the race).
    """
    return session.execute(
        insert(LegacyUserMapping)
        .values(legacy_user_id=legacy_user_id, user_id=user_id)
        .on_conflict_do_nothing(index_elements=[LegacyUserMapping.legacy_user_id])
        .returning(col(LegacyUserMapping.user_id))
    ).scalar_one_or_none()


def create_legacy_user_policy_mapping(
    session: Session,
    *,
    revision: LegacyUserPolicyRevision,
    user_policy_id: UUID,
    fingerprint_version: int,
) -> UUID | None:
    """Map a v1 saved policy to its v2 association at the revision's source revision.

    Return the new mapping id, or None when this v1 saved policy is already
    mapped in this country.
    """
    return session.execute(
        insert(LegacyUserPolicyMapping)
        .values(
            country_id=revision.country_id,
            legacy_user_policy_id=revision.legacy_user_policy_id,
            user_policy_id=user_policy_id,
            last_applied_source_revision=revision.source_revision,
            fingerprint_version=fingerprint_version,
            fingerprint_sha256=revision.fingerprint,
        )
        .on_conflict_do_nothing(
            constraint="uq_legacy_user_policy_mappings_country_legacy"
        )
        .returning(col(LegacyUserPolicyMapping.id))
    ).scalar_one_or_none()
