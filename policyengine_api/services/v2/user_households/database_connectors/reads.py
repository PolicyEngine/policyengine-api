"""Database reads for v2 user-household associations."""

from __future__ import annotations

from uuid import UUID

from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import Household, User, UserHouseholdAssociation


def read_user(session: Session, user_id: UUID) -> User | None:
    return session.get(User, user_id)


def read_household_for_association(
    session: Session,
    household_id: UUID,
) -> Household | None:
    return session.exec(
        select(Household).where(Household.id == household_id)
    ).one_or_none()


def read_user_household_row(
    session: Session,
    *,
    country_id: str,
    association_id: UUID,
) -> UserHouseholdAssociation | None:
    return session.exec(
        select(UserHouseholdAssociation).where(
            UserHouseholdAssociation.id == association_id,
            UserHouseholdAssociation.country_id == country_id,
        )
    ).one_or_none()


def read_user_household_rows(
    session: Session,
    *,
    country_id: str,
    user_id: UUID,
    household_id: UUID | None,
    offset: int,
    limit: int,
) -> list[UserHouseholdAssociation]:
    statement = select(UserHouseholdAssociation).where(
        UserHouseholdAssociation.country_id == country_id,
        UserHouseholdAssociation.user_id == user_id,
    )
    if household_id is not None:
        statement = statement.where(
            UserHouseholdAssociation.household_id == household_id
        )
    return list(
        session.exec(
            statement.order_by(
                col(UserHouseholdAssociation.created_at),
                col(UserHouseholdAssociation.id),
            )
            .offset(offset)
            .limit(limit + 1)
        ).all()
    )
