"""SQLite-backed helpers for signed-in user service tests."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, create_engine

from policyengine_api.data.v2.models import (
    V2_METADATA,
    Household,
    LegacyHouseholdMapping,
    LegacyPolicyMapping,
    Parameter,
    ParameterValue,
    Policy,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.services.v2.identity.types import (
    UnauthenticatedPrincipal,
    UserPrincipal,
)
from policyengine_api.services.v2.legacy_refs.types import LegacyRecordKind
from policyengine_api.services.v2.legacy_refs.validators import (
    require_legacy_references,
)
from tests.fixtures.v2_countries import add_listed_countries

if TYPE_CHECKING:
    from collections.abc import Collection, Iterator, Mapping

ISSUER = "https://auth.example.test/"
ALICE = UserPrincipal(issuer=ISSUER, subject="google-oauth2|alice")
BOB = UserPrincipal(issuer=ISSUER, subject="google-oauth2|bob")
SIGNED_OUT_BROWSER = UnauthenticatedPrincipal(
    user_id=UUID("3d6f0a8e-5b2c-4e1f-9d7a-2c4b6e8f0a13")
)
OTHER_SIGNED_OUT_BROWSER = UnauthenticatedPrincipal(
    user_id=UUID("9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d")
)
MAPPED_LEGACY_POLICY_ID = 501
MAPPED_LEGACY_HOUSEHOLD_ID = 601


class FakeLegacyReferences:
    """In-memory v1 existence checks keyed by country and record kind."""

    def __init__(
        self,
        existing: Mapping[tuple[str, LegacyRecordKind], Collection[int]],
    ) -> None:
        self._existing = {key: frozenset(ids) for key, ids in existing.items()}
        self.calls: list[tuple[str, dict[LegacyRecordKind, list[int]]]] = []

    def existing_ids(
        self,
        *,
        country_id: str,
        requested: Mapping[LegacyRecordKind, Collection[int]],
    ) -> dict[LegacyRecordKind, frozenset[int]]:
        self.calls.append(
            (country_id, {kind: sorted(ids) for kind, ids in requested.items()})
        )
        return {
            kind: frozenset(ids) & self._existing.get((country_id, kind), frozenset())
            for kind, ids in requested.items()
        }

    def require_existing(
        self,
        *,
        country_id: str,
        requested: Mapping[LegacyRecordKind, Collection[int]],
    ) -> None:
        existing = self.existing_ids(country_id=country_id, requested=requested)
        for kind, ids in requested.items():
            require_legacy_references(
                kind,
                country_id=country_id,
                requested=ids,
                existing=existing[kind],
            )


def default_legacy_references() -> FakeLegacyReferences:
    return FakeLegacyReferences(
        {
            ("us", LegacyRecordKind.POLICY): {1, 2, 3, MAPPED_LEGACY_POLICY_ID},
            ("us", LegacyRecordKind.HOUSEHOLD): {10, 11, MAPPED_LEGACY_HOUSEHOLD_ID},
            ("us", LegacyRecordKind.SIMULATION): {613, 614},
            ("us", LegacyRecordKind.REPORT): {615, 616},
            ("uk", LegacyRecordKind.POLICY): {7},
        }
    )


@dataclass(frozen=True)
class V2Store:
    sessions: sessionmaker[Session]
    policy_id: UUID
    uk_policy_id: UUID
    household_id: UUID
    uk_household_id: UUID


@contextmanager
def v2_store() -> Iterator[V2Store]:
    """Create an isolated SQLite v2 schema with mirrored v1 records."""
    engine = create_engine("sqlite://")

    @sa.event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
        # SQLAlchemy's documented pysqlite recipe: let SQLAlchemy own BEGIN so
        # provisioning savepoints behave as they do on Postgres.
        dbapi_connection.isolation_level = None

    @sa.event.listens_for(engine, "begin")
    def begin_transaction(connection) -> None:
        connection.exec_driver_sql("BEGIN")

    V2_METADATA.create_all(engine)
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    with sessions() as session:
        add_listed_countries(session)
    with sessions.begin() as session:
        model = TaxBenefitModel(name="policyengine-us")
        version = TaxBenefitModelVersion(
            model=model,
            version="5.2.0",
            current_law_id=1,
            metadata_time_periods=[2026],
        )
        parameter = Parameter(
            name="gov.example.rate", tax_benefit_model_version=version
        )
        policy = Policy(
            country_id="us",
            tax_benefit_model=model,
            tax_benefit_model_version=version,
            canonicalization_version=1,
            content_hash="a" * 64,
        )
        uk_policy = Policy(
            country_id="uk",
            tax_benefit_model=model,
            tax_benefit_model_version=version,
            canonicalization_version=1,
            content_hash="b" * 64,
        )
        value = ParameterValue(
            parameter=parameter,
            policy=policy,
            value_json=0.2,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
        )
        household = Household(
            country_id="us",
            default_year=2026,
            household_data={"people": [], "household": []},
            canonicalization_version=1,
            content_hash="c" * 64,
        )
        uk_household = Household(
            country_id="uk",
            default_year=2026,
            household_data={"people": [], "household": []},
            canonicalization_version=1,
            content_hash="f" * 64,
        )
        session.add_all([value, uk_policy, household, uk_household])
        session.flush()
        session.add_all(
            [
                LegacyPolicyMapping(
                    country_id="us",
                    legacy_policy_id=MAPPED_LEGACY_POLICY_ID,
                    policy_id=policy.id,
                    source_policy_hash="hash",
                ),
                LegacyHouseholdMapping(
                    country_id="us",
                    legacy_household_id=MAPPED_LEGACY_HOUSEHOLD_ID,
                    household_id=household.id,
                    source_api_version="1",
                    fingerprint_version=1,
                    fingerprint_sha256="d" * 64,
                ),
            ]
        )
        session.flush()
        store = V2Store(
            sessions=sessions,
            policy_id=policy.id,
            uk_policy_id=uk_policy.id,
            household_id=household.id,
            uk_household_id=uk_household.id,
        )
    try:
        yield store
    finally:
        engine.dispose()
