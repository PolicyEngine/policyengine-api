"""Database selections used by v2 user-policy operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import (
    LegacyPolicyMapping,
    LegacyUserMapping,
    LegacyUserPolicyMapping,
    Policy,
    User,
    UserPolicy,
)

if TYPE_CHECKING:
    from collections.abc import Collection
    from uuid import UUID


def read_user(session: Session, user_id: UUID) -> User | None:
    """Return the v2 user with this id, or None."""
    return session.get(User, user_id)


def read_policy_for_association(session: Session, policy_id: UUID) -> Policy | None:
    """Return the policy with this id in any country, or None."""
    return session.exec(select(Policy).where(Policy.id == policy_id)).one_or_none()


def read_legacy_user_mapping(
    session: Session, legacy_user_id: str, *, lock: bool
) -> LegacyUserMapping | None:
    """Return the mapping for a v1 user id, or None; ``lock`` selects it FOR UPDATE."""
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
    """Return the mapping for a v1 saved policy in this country, or None.

    With ``lock``, the row is selected FOR UPDATE so concurrent revisions of the
    same v1 saved policy serialize on it.
    """
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
    """Return the association a mapping points to, in the mapping's country, or None."""
    return session.exec(
        select(UserPolicy).where(
            UserPolicy.id == mapping.user_policy_id,
            UserPolicy.country_id == mapping.country_id,
        )
    ).one_or_none()


def read_owned_user_policy_row(
    session: Session,
    *,
    user_id: UUID,
    country_id: str,
    association_id: UUID,
) -> UserPolicy | None:
    """Return the user's association with this id in this country, or None."""
    return session.exec(
        select(UserPolicy).where(
            UserPolicy.id == association_id,
            UserPolicy.country_id == country_id,
            UserPolicy.user_id == user_id,
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
    legacy_policy_id: int | None = None,
) -> list[UserPolicy]:
    """Return up to ``limit + 1`` of a user's associations in creation order.

    With ``policy_id`` or ``legacy_policy_id``, only associations to that policy
    are returned. The extra row lets the caller report whether another page
    exists.
    """
    statement = select(UserPolicy).where(
        UserPolicy.country_id == country_id,
        UserPolicy.user_id == user_id,
    )
    if policy_id is not None:
        statement = statement.where(UserPolicy.policy_id == policy_id)
    if legacy_policy_id is not None:
        statement = statement.where(UserPolicy.legacy_policy_id == legacy_policy_id)
    return list(
        session.exec(
            statement.order_by(col(UserPolicy.created_at), col(UserPolicy.id))
            .offset(offset)
            .limit(limit + 1)
        ).all()
    )


def read_all_user_policy_rows(session: Session, *, user_id: UUID) -> list[UserPolicy]:
    """Return every association the user owns, in any country, in creation order."""
    return list(
        session.exec(
            select(UserPolicy)
            .where(UserPolicy.user_id == user_id)
            .order_by(col(UserPolicy.created_at), col(UserPolicy.id))
        ).all()
    )


def read_user_policy_mirror_exists(session: Session, *, association_id: UUID) -> bool:
    """Return whether the Stage 10 v1 saved-policy mirror maintains the association."""
    return (
        session.exec(
            select(LegacyUserPolicyMapping.id).where(
                LegacyUserPolicyMapping.user_policy_id == association_id
            )
        ).first()
        is not None
    )


def read_mirrored_policy_ids(
    session: Session,
    *,
    country_id: str,
    legacy_policy_ids: Collection[int],
) -> dict[int, UUID]:
    """Return v2 policy UUIDs for v1 policies that the Stage 10 mirror copied."""
    if not legacy_policy_ids:
        return {}
    rows = session.exec(
        select(
            LegacyPolicyMapping.legacy_policy_id, LegacyPolicyMapping.policy_id
        ).where(
            LegacyPolicyMapping.country_id == country_id,
            col(LegacyPolicyMapping.legacy_policy_id).in_(
                sorted(set(legacy_policy_ids))
            ),
        )
    ).all()
    return {int(legacy_policy_id): policy_id for legacy_policy_id, policy_id in rows}
