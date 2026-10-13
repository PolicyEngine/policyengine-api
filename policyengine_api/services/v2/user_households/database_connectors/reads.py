"""Database reads for v2 user-household associations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import (
    Household,
    LegacyHouseholdMapping,
    UserHouseholdAssociation,
)

if TYPE_CHECKING:
    from collections.abc import Collection
    from uuid import UUID


def read_household_for_association(
    session: Session,
    household_id: UUID,
) -> Household | None:
    """Return the household with this id in any country, or None."""
    return session.exec(
        select(Household).where(Household.id == household_id)
    ).one_or_none()


def read_owned_user_household_row(
    session: Session,
    *,
    user_id: UUID,
    country_id: str,
    association_id: UUID,
) -> UserHouseholdAssociation | None:
    """Return the association with this id in this country, or None."""
    return session.exec(
        select(UserHouseholdAssociation).where(
            UserHouseholdAssociation.id == association_id,
            UserHouseholdAssociation.country_id == country_id,
            UserHouseholdAssociation.user_id == user_id,
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
    legacy_household_id: int | None = None,
) -> list[UserHouseholdAssociation]:
    """Return up to ``limit + 1`` of a user's associations in creation order.

    With ``household_id``, only associations to that household are returned. The
    extra row lets the caller report whether another page exists.
    """
    statement = select(UserHouseholdAssociation).where(
        UserHouseholdAssociation.country_id == country_id,
        UserHouseholdAssociation.user_id == user_id,
    )
    if household_id is not None:
        statement = statement.where(
            UserHouseholdAssociation.household_id == household_id
        )
    if legacy_household_id is not None:
        statement = statement.where(
            UserHouseholdAssociation.legacy_household_id == legacy_household_id
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


def read_all_user_household_rows(
    session: Session, *, user_id: UUID
) -> list[UserHouseholdAssociation]:
    return list(
        session.exec(
            select(UserHouseholdAssociation)
            .where(UserHouseholdAssociation.user_id == user_id)
            .order_by(
                col(UserHouseholdAssociation.created_at),
                col(UserHouseholdAssociation.id),
            )
        ).all()
    )


def read_copied_household_ids(
    session: Session,
    *,
    country_id: str,
    legacy_household_ids: Collection[int],
) -> dict[int, UUID]:
    """Return v2 household UUIDs for v1 households that Stage 11 copied."""

    if not legacy_household_ids:
        return {}
    rows = session.exec(
        select(
            LegacyHouseholdMapping.legacy_household_id,
            LegacyHouseholdMapping.household_id,
        ).where(
            LegacyHouseholdMapping.country_id == country_id,
            col(LegacyHouseholdMapping.legacy_household_id).in_(
                sorted(set(legacy_household_ids))
            ),
        )
    ).all()
    return {
        int(legacy_household_id): household_id
        for legacy_household_id, household_id in rows
    }
