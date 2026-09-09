"""Database inserts for immutable v2 households."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col

from policyengine_api.data.v2.models import Household, LegacyHouseholdMapping
from policyengine_api.services.v2.households.types import HouseholdCreationInput


def create_household(
    session: Session,
    household_input: HouseholdCreationInput,
    *,
    canonicalization_version: int,
    content_hash: str,
) -> UUID | None:
    household_id = uuid4()
    statement = (
        insert(Household)
        .values(
            id=household_id,
            country_id=household_input.country_id,
            default_year=household_input.default_year,
            household_data=household_input.household_data,
            canonicalization_version=canonicalization_version,
            content_hash=content_hash,
        )
        .on_conflict_do_nothing(
            constraint="uq_households_canonicalization_content_hash"
        )
        .returning(col(Household.id))
    )
    return session.execute(statement).scalar_one_or_none()


def create_legacy_household_mapping(
    session: Session,
    *,
    country_id: str,
    legacy_household_id: int,
    household_id: UUID,
    source_api_version: str,
    fingerprint_version: int,
    fingerprint_sha256: str,
) -> UUID | None:
    mapping_id = uuid4()
    statement = (
        insert(LegacyHouseholdMapping)
        .values(
            id=mapping_id,
            country_id=country_id,
            legacy_household_id=legacy_household_id,
            household_id=household_id,
            source_api_version=source_api_version,
            fingerprint_version=fingerprint_version,
            fingerprint_sha256=fingerprint_sha256,
        )
        .on_conflict_do_nothing(
            constraint="uq_legacy_household_mappings_country_legacy"
        )
        .returning(col(LegacyHouseholdMapping.id))
    )
    return session.execute(statement).scalar_one_or_none()
