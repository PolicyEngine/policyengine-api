"""Database reads for v2 household operations."""

from __future__ import annotations

from uuid import UUID

from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import Household, LegacyHouseholdMapping


def read_household_by_content_identity(
    session: Session, *, canonicalization_version: int, content_hash: str
) -> Household | None:
    return session.exec(
        select(Household).where(
            Household.canonicalization_version == canonicalization_version,
            Household.content_hash == content_hash,
        )
    ).one_or_none()


def read_household_row(
    session: Session, *, country_id: str, household_id: UUID
) -> Household | None:
    return session.exec(
        select(Household).where(
            Household.id == household_id,
            Household.country_id == country_id,
        )
    ).one_or_none()


def read_household_rows(
    session: Session,
    *,
    country_id: str,
    default_year: int | None,
    offset: int,
    limit: int,
) -> list[Household]:
    statement = select(Household).where(Household.country_id == country_id)
    if default_year is not None:
        statement = statement.where(Household.default_year == default_year)
    return list(
        session.exec(
            statement.order_by(col(Household.created_at), col(Household.id))
            .offset(offset)
            .limit(limit + 1)
        ).all()
    )


def read_legacy_household_mapping(
    session: Session,
    *,
    country_id: str,
    legacy_household_id: int,
    lock: bool,
) -> LegacyHouseholdMapping | None:
    statement = select(LegacyHouseholdMapping).where(
        LegacyHouseholdMapping.country_id == country_id,
        LegacyHouseholdMapping.legacy_household_id == legacy_household_id,
    )
    if lock:
        statement = statement.with_for_update()
    return session.exec(statement).one_or_none()
