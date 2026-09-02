"""Database creates used by v2 user-policy association operations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col

from policyengine_api.data.v2.models import (
    LegacyUserMapping,
    LegacyUserPolicyMapping,
    User,
    UserPolicy,
)
from policyengine_api.services.v2.user_policies.commands import (
    UserPolicyCreateCommand,
)


def create_user_policy(
    session: Session,
    command: UserPolicyCreateCommand,
) -> UserPolicy:
    """Create one independently identified association."""

    association = UserPolicy(**command.model_dump())
    session.add(association)
    session.flush()
    session.refresh(association)
    return association


def create_transition_user(
    session: Session,
    *,
    primary_country: str,
) -> User:
    """Create a minimal v2 user for one legacy identity."""

    user = User(primary_country=primary_country)
    session.add(user)
    session.flush()
    return user


def create_legacy_user_mapping(
    session: Session,
    *,
    legacy_user_id: str,
    user_id: UUID,
) -> UUID | None:
    """Create one legacy-user mapping, or return none after a conflict."""

    return session.execute(
        insert(LegacyUserMapping)
        .values(legacy_user_id=legacy_user_id, user_id=user_id)
        .on_conflict_do_nothing(index_elements=[LegacyUserMapping.legacy_user_id])
        .returning(col(LegacyUserMapping.user_id))
    ).scalar_one_or_none()


def create_legacy_user_policy_mapping(
    session: Session,
    *,
    country_id: str,
    legacy_user_policy_id: int,
    user_policy_id: UUID,
    source_revision: int,
    fingerprint_version: int,
    fingerprint: str,
) -> UUID | None:
    """Create one legacy association mapping, or return none after a conflict."""

    return session.execute(
        insert(LegacyUserPolicyMapping)
        .values(
            country_id=country_id,
            legacy_user_policy_id=legacy_user_policy_id,
            user_policy_id=user_policy_id,
            last_applied_source_revision=source_revision,
            fingerprint_version=fingerprint_version,
            fingerprint_sha256=fingerprint,
        )
        .on_conflict_do_nothing(
            constraint="uq_legacy_user_policy_mappings_country_legacy"
        )
        .returning(col(LegacyUserPolicyMapping.id))
    ).scalar_one_or_none()
