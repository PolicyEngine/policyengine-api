"""Database selections used by v2 user-policy operations."""

from __future__ import annotations

from uuid import UUID

from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import (
    LegacyUserMapping,
    LegacyUserPolicyMapping,
    Policy,
    User,
    UserPolicy,
)


def read_user(session: Session, user_id: UUID) -> User | None:
    return session.get(User, user_id)


def read_policy_for_association(session: Session, policy_id: UUID) -> Policy | None:
    return session.exec(select(Policy).where(Policy.id == policy_id)).one_or_none()


def read_legacy_user_mapping(
    session: Session, legacy_user_id: str, *, lock: bool
) -> LegacyUserMapping | None:
    statement = select(LegacyUserMapping).where(
        LegacyUserMapping.legacy_user_id == legacy_user_id
    )
    if lock:
        statement = statement.with_for_update()
    return session.exec(statement).one_or_none()


def read_legacy_user_policy_mapping(
    session: Session,
    *,
    country_id: str,
    legacy_user_policy_id: int,
    lock: bool,
) -> LegacyUserPolicyMapping | None:
    statement = select(LegacyUserPolicyMapping).where(
        LegacyUserPolicyMapping.country_id == country_id,
        LegacyUserPolicyMapping.legacy_user_policy_id == legacy_user_policy_id,
    )
    if lock:
        statement = statement.with_for_update()
    return session.exec(statement).one_or_none()


def read_mapped_user_policy(
    session: Session, mapping: LegacyUserPolicyMapping
) -> UserPolicy | None:
    return session.exec(
        select(UserPolicy).where(
            UserPolicy.id == mapping.user_policy_id,
            UserPolicy.country_id == mapping.country_id,
        )
    ).one_or_none()


def read_user_policy_row(
    session: Session, *, country_id: str, association_id: UUID
) -> UserPolicy | None:
    return session.exec(
        select(UserPolicy).where(
            UserPolicy.id == association_id,
            UserPolicy.country_id == country_id,
        )
    ).one_or_none()


def read_user_policy_rows(
    session: Session,
    *,
    country_id: str,
    user_id: UUID,
    policy_id: UUID | None,
    offset: int,
    limit: int,
) -> list[UserPolicy]:
    statement = select(UserPolicy).where(
        UserPolicy.country_id == country_id,
        UserPolicy.user_id == user_id,
    )
    if policy_id is not None:
        statement = statement.where(UserPolicy.policy_id == policy_id)
    return list(
        session.exec(
            statement.order_by(col(UserPolicy.created_at), col(UserPolicy.id))
            .offset(offset)
            .limit(limit + 1)
        ).all()
    )
