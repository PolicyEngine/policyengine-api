"""Schema and persistence tests for v2 household records."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from policyengine_api.data.v1_models import HouseholdMirrorEvent
from policyengine_api.data.v2.models import (
    Household,
    LegacyHouseholdMapping,
    User,
    UserHouseholdAssociation,
)
from tests.fixtures.database_sessions import sqlite_v1_sessions, sqlite_v2_sessions
from tests.fixtures.v2_countries import add_listed_countries
from tests.unit.v2.v2_schema_reading import (
    model_columns,
    stored_v1_schema,
    stored_v2_table,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlmodel import Session


@contextmanager
def _session() -> Iterator[Session]:
    """Yield a Session of a SQLite v2 schema that enforces foreign keys."""
    with sqlite_v2_sessions(foreign_keys=True) as sessions:
        with sessions(expire_on_commit=True) as session:
            add_listed_countries(session)
        with sessions(expire_on_commit=True) as session:
            yield session


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
    households = model_columns("households")
    stored_households = stored_v2_table("households")

    assert {"country", "year", "label"}.isdisjoint(households.keys())
    assert {
        "country_id",
        "default_year",
        "household_data",
        "canonicalization_version",
        "content_hash",
        "created_at",
        "updated_at",
    }.issubset(households.keys())
    assert households.default_year.nullable
    assert isinstance(
        households.household_data.type.dialect_impl(postgresql.dialect()),
        postgresql.JSONB,
    )
    unique_columns = stored_households.unique_column_sets
    assert ("id", "country_id") in unique_columns
    assert ("canonicalization_version", "content_hash") in unique_columns
    assert "ix_households_country_default_year_created_id" in (
        stored_households.indexes
    )


def test_user_household_is_an_independent_country_scoped_association() -> None:
    associations = model_columns("user_household_associations")
    stored_associations = stored_v2_table("user_household_associations")

    assert {"country", "label"}.isdisjoint(associations.keys())
    assert {"country_id", "name", "description"}.issubset(associations.keys())
    unique_columns = stored_associations.unique_column_sets
    assert ("user_id", "household_id") not in unique_columns
    assert ("id", "country_id") in unique_columns
    household_country = stored_associations.foreign_key_named(
        "fk_user_household_associations_household_country"
    )
    assert household_country.columns == ("household_id", "country_id")
    assert household_country.targets == ("households.id", "households.country_id")
    assert household_country.ondelete == "RESTRICT"
    assert (
        sa.inspect(UserHouseholdAssociation).relationships["user"].back_populates
        == "household_associations"
    )


def test_legacy_household_mapping_is_many_to_one_by_destination() -> None:
    columns = model_columns("legacy_household_mappings")
    mappings = stored_v2_table("legacy_household_mappings")

    unique_columns = mappings.unique_column_sets
    assert ("country_id", "legacy_household_id") in unique_columns
    assert ("household_id",) not in unique_columns
    assert columns.source_api_version.type.length == 255
    assert columns.fingerprint_sha256.type.length == 64
    household_country = mappings.foreign_keys[0]
    assert household_country.name == "fk_legacy_household_mappings_household_country"
    assert household_country.ondelete == "RESTRICT"


def test_v1_household_event_contains_one_create_snapshot_without_revision() -> None:
    event = model_columns(HouseholdMirrorEvent)
    stored_event = stored_v1_schema()[HouseholdMirrorEvent.__tablename__]

    assert {"source_revision", "event_type"}.isdisjoint(event.keys())
    assert {
        "country_id",
        "legacy_household_id",
        "payload_schema_version",
        "payload_json",
        "source_fingerprint_sha256",
        "created_at",
        "processed_at",
    }.issubset(event.keys())
    assert ("country_id", "legacy_household_id") in stored_event.unique_column_sets
    assert "ix_household_mirror_events_pending_age" in stored_event.indexes


def test_household_hash_uniqueness_and_legacy_null_year() -> None:
    with _session() as session:
        legacy = _household(default_year=None)
        duplicate = _household(default_year=2026)
        session.add_all([legacy, duplicate])
        with pytest.raises(IntegrityError):
            session.commit()


def test_association_duplicates_are_allowed_but_country_must_match() -> None:
    with _session() as session:
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


def test_legacy_mappings_allow_many_sources_and_restrict_household_deletion() -> None:
    with _session() as session:
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


def test_v1_event_identity_is_unique_and_failed_transaction_rolls_back() -> None:
    with sqlite_v1_sessions() as sessions:
        payload = {
            "country_id": "us",
            "legacy_household_id": 100,
            "label": None,
            "api_version": "1.0.0",
            "household_json": {"people": {}},
            "household_hash": "source-hash",
        }
        with sessions(expire_on_commit=True) as session:
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
            assert session.scalars(select(HouseholdMirrorEvent)).all() == []


def test_household_timestamps_are_database_compatible() -> None:
    with _session() as session:
        household = _household(content_hash="d" * 64)
        session.add(household)
        session.commit()
        assert isinstance(household.created_at, datetime)
        assert isinstance(household.updated_at, datetime)
