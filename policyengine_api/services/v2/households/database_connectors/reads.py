"""Database reads for v2 household operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Session, select

from policyengine_api.data.v2.models import Household, LegacyHouseholdMapping

if TYPE_CHECKING:
    from uuid import UUID


def read_household_by_content_identity(
    session: Session, *, canonicalization_version: int, content_hash: str
) -> Household | None:
    """Return the household with this canonical version and content hash, or None."""
    return session.exec(
        select(Household).where(
            Household.canonicalization_version == canonicalization_version,
            Household.content_hash == content_hash,
        )
    ).one_or_none()


def read_household_row(
    session: Session, *, country_id: str, household_id: UUID
) -> Household | None:
    """Return the household with this id in this country, or None."""
    return session.exec(
        select(Household).where(
            Household.id == household_id,
            Household.country_id == country_id,
        )
    ).one_or_none()


def read_legacy_household_mapping(
    session: Session,
    *,
    country_id: str,
    legacy_household_id: int,
    lock: bool,
) -> LegacyHouseholdMapping | None:
    """Return the v2 mapping for a v1 household id, or None.

    With ``lock``, the row is selected FOR UPDATE so concurrent copies of the same
    v1 household serialize on it.
    """
    statement = select(LegacyHouseholdMapping).where(
        LegacyHouseholdMapping.country_id == country_id,
        LegacyHouseholdMapping.legacy_household_id == legacy_household_id,
    )
    if lock:
        statement = statement.with_for_update()
    return session.exec(statement).one_or_none()
