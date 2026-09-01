"""Country-scoped v2 user-policy association reads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlmodel import Session, select

from policyengine_api.data.v2.models import UserPolicy


class UserPolicyNotFoundError(LookupError):
    """Raised when an association is absent from the selected country."""


@dataclass(frozen=True)
class UserPolicyRead:
    id: UUID
    country_id: str
    user_id: UUID
    policy_id: UUID
    name: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class UserPolicyPage:
    items: tuple[UserPolicyRead, ...]
    offset: int
    limit: int
    has_more: bool


def association_read(association: UserPolicy) -> UserPolicyRead:
    return UserPolicyRead(
        id=association.id,
        country_id=association.country_id,
        user_id=association.user_id,
        policy_id=association.policy_id,
        name=association.name,
        description=association.description,
        created_at=association.created_at,
        updated_at=association.updated_at,
    )


def get_user_policy_row(
    session: Session,
    *,
    country_id: str,
    association_id: UUID,
) -> UserPolicy:
    association = session.exec(
        select(UserPolicy).where(
            UserPolicy.id == association_id,
            UserPolicy.country_id == country_id,
        )
    ).one_or_none()
    if association is None:
        raise UserPolicyNotFoundError(
            f"user-policy association {association_id} was not found"
        )
    return association


def read_user_policy(
    session: Session,
    *,
    country_id: str,
    association_id: UUID,
) -> UserPolicyRead:
    """Read one association only under its stored country."""

    return association_read(
        get_user_policy_row(
            session,
            country_id=country_id,
            association_id=association_id,
        )
    )


def list_user_policies(
    session: Session,
    *,
    country_id: str,
    user_id: UUID,
    policy_id: UUID | None = None,
    offset: int = 0,
    limit: int = 100,
) -> UserPolicyPage:
    """Read one deterministic bounded page for a v2 user UUID."""

    statement = select(UserPolicy).where(
        UserPolicy.country_id == country_id,
        UserPolicy.user_id == user_id,
    )
    if policy_id is not None:
        statement = statement.where(UserPolicy.policy_id == policy_id)
    rows = session.exec(
        statement.order_by(UserPolicy.created_at, UserPolicy.id)
        .offset(offset)
        .limit(limit + 1)
    ).all()
    has_more = len(rows) > limit
    return UserPolicyPage(
        items=tuple(association_read(row) for row in rows[:limit]),
        offset=offset,
        limit=limit,
        has_more=has_more,
    )
