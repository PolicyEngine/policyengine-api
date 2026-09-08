"""Schema and persistence tests for v2 household records."""

from __future__ import annotations

from datetime import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, create_engine, select

from policyengine_api.data.v1_models import HouseholdMirrorEvent
from policyengine_api.data.v2.models import (
    Household,
    LegacyHouseholdMapping,
    User,
    UserHouseholdAssociation,
    V2_METADATA,
)


def _engine():
    engine = create_engine("sqlite://")

    @sa.event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    V2_METADATA.create_all(engine)
    return engine


def _household(
    *,
    country_id: str = "us",
    default_year: int | None = 2026,
    content_hash: str = "a" * 64,
) -> Household:
    return Household(
        country_id=country_id,
        default_year=default_year,
        household_data={"people": [], "household": []},
        canonicalization_version=1,
        content_hash=content_hash,
    )


def test_household_schema_uses_jsonb_and_versioned_content_identity() -> None:
    households = V2_METADATA.tables["households"]

    assert {"country", "year", "label"}.isdisjoint(households.c.keys())
    assert {
        "country_id",
        "default_year",
        "household_data",
        "canonicalization_version",
        "content_hash",
        "created_at",
        "updated_at",
    }.issubset(households.c.keys())
    assert households.c.default_year.nullable
    assert isinstance(
        households.c.household_data.type.dialect_impl(postgresql.dialect()),
        postgresql.JSONB,
    )
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in households.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    assert ("id", "country_id") in unique_columns
    assert ("canonicalization_version", "content_hash") in unique_columns
    assert "ix_households_country_default_year_created_id" in {
        index.name for index in households.indexes
    }


def test_user_household_is_an_independent_country_scoped_association() -> None:
    associations = V2_METADATA.tables["user_household_associations"]

    assert {"country", "label"}.isdisjoint(associations.c.keys())
    assert {"country_id", "name", "description"}.issubset(associations.c.keys())
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in associations.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    assert ("user_id", "household_id") not in unique_columns
    assert ("id", "country_id") in unique_columns
    household_country = next(
        constraint
        for constraint in associations.foreign_key_constraints
        if constraint.name == "fk_user_household_associations_household_country"
    )
    assert [column.name for column in household_country.columns] == [
        "household_id",
        "country_id",
    ]
    assert [element.target_fullname for element in household_country.elements] == [
        "households.id",
        "households.country_id",
    ]
    assert household_country.ondelete == "RESTRICT"
    assert (
        sa.inspect(UserHouseholdAssociation).relationships["user"].back_populates
        == "household_associations"
    )


def test_legacy_household_mapping_is_many_to_one_by_destination() -> None:
    mappings = V2_METADATA.tables["legacy_household_mappings"]

    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in mappings.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    assert ("country_id", "legacy_household_id") in unique_columns
    assert ("household_id",) not in unique_columns
    assert mappings.c.source_api_version.type.length == 255
    assert mappings.c.fingerprint_sha256.type.length == 64
    household_country = next(iter(mappings.foreign_key_constraints))
    assert household_country.name == "fk_legacy_household_mappings_household_country"
    assert household_country.ondelete == "RESTRICT"


def test_v1_household_event_contains_one_create_snapshot_without_revision() -> None:
    event = HouseholdMirrorEvent.__table__

    assert {"source_revision", "event_type"}.isdisjoint(event.c.keys())
    assert {
        "country_id",
        "legacy_household_id",
        "payload_schema_version",
        "payload_json",
        "source_fingerprint_sha256",
        "created_at",
        "processed_at",
    }.issubset(event.c.keys())
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in event.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    assert ("country_id", "legacy_household_id") in unique_columns
    assert "ix_household_mirror_events_pending_age" in {
        index.name for index in event.indexes
    }


def test_household_hash_uniqueness_and_legacy_null_year() -> None:
    engine = _engine()
    try:
        with Session(engine) as session:
            legacy = _household(default_year=None)
            duplicate = _household(default_year=2026)
            session.add_all([legacy, duplicate])
            with pytest.raises(IntegrityError):
                session.commit()
    finally:
        engine.dispose()


def test_association_duplicates_are_allowed_but_country_must_match() -> None:
    engine = _engine()
    try:
        with Session(engine) as session:
            household = _household(content_hash="b" * 64)
            user = User(primary_country="us")
            session.add_all([household, user])
            session.commit()
            first = UserHouseholdAssociation(
                country_id="us",
                user_id=user.id,
                household_id=household.id,
                name="First",
            )
            second = UserHouseholdAssociation(
                country_id="us",
                user_id=user.id,
                household_id=household.id,
                name="Second",
            )
            session.add_all([first, second])
            session.commit()
            assert first.id != second.id

            session.add(
                UserHouseholdAssociation(
                    country_id="uk",
                    user_id=user.id,
                    household_id=household.id,
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
    finally:
        engine.dispose()


def test_legacy_mappings_allow_many_sources_and_restrict_household_deletion() -> None:
    engine = _engine()
    try:
        with Session(engine) as session:
            household = _household(content_hash="c" * 64)
            session.add(household)
            session.commit()
            session.add_all(
                [
                    LegacyHouseholdMapping(
                        country_id="us",
                        legacy_household_id=101,
                        household_id=household.id,
                        source_api_version="1.0.0",
                        fingerprint_version=1,
                        fingerprint_sha256="1" * 64,
                    ),
                    LegacyHouseholdMapping(
                        country_id="us",
                        legacy_household_id=102,
                        household_id=household.id,
                        source_api_version="1.0.0",
                        fingerprint_version=1,
                        fingerprint_sha256="2" * 64,
                    ),
                ]
            )
            session.commit()
            assert len(household.legacy_mappings) == 2

            session.delete(household)
            with pytest.raises(IntegrityError):
                session.commit()
    finally:
        engine.dispose()


def test_v1_event_identity_is_unique_and_failed_transaction_rolls_back() -> None:
    engine = create_engine("sqlite://")
    HouseholdMirrorEvent.__table__.create(engine)
    try:
        payload = {
            "country_id": "us",
            "legacy_household_id": 100,
            "label": None,
            "api_version": "1.0.0",
            "household_json": {"people": {}},
            "household_hash": "source-hash",
        }
        with Session(engine) as session:
            session.add_all(
                [
                    HouseholdMirrorEvent(
                        country_id="us",
                        legacy_household_id=100,
                        payload_schema_version=1,
                        payload_json=payload,
                        source_fingerprint_sha256="1" * 64,
                    ),
                    HouseholdMirrorEvent(
                        country_id="us",
                        legacy_household_id=100,
                        payload_schema_version=1,
                        payload_json=payload,
                        source_fingerprint_sha256="1" * 64,
                    ),
                ]
            )
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
            assert session.exec(select(HouseholdMirrorEvent)).all() == []
    finally:
        engine.dispose()


def test_household_timestamps_are_database_compatible() -> None:
    engine = _engine()
    try:
        with Session(engine) as session:
            household = _household(content_hash="d" * 64)
            session.add(household)
            session.commit()
            assert isinstance(household.created_at, datetime)
            assert isinstance(household.updated_at, datetime)
    finally:
        engine.dispose()
