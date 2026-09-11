"""Canonical SPM household events on disposable MySQL and PostgreSQL.

Use the local, Alembic-migrated targets required by test_mysql_policy_dual_write.
Only scientific bundle selection is deterministic; storage, JSON conversion,
fingerprints, transactions, mirror replay, and content identity remain real.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import json
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.exc import DataError
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data.v1_models import (
    Household as V1Household,
    HouseholdMirrorEvent,
)
from policyengine_api.data.v2.models import Household, LegacyHouseholdMapping
from policyengine_api.services import household_service
from policyengine_api.services.household_mirroring import (
    HouseholdMirrorUnavailableError,
    process_household_event_after_commit,
)
from policyengine_api.services.household_service import HouseholdService
from policyengine_api.services.v2.households.database_session import (
    HouseholdDatabaseSession,
)
from policyengine_api.services.v2.households.services import V2HouseholdService
from policyengine_api.services.v2.households.transformations import (
    legacy_household_fingerprint,
)
from policyengine_api.utils import hash_object
from tests.integration.test_mysql_policy_dual_write import _mysql_url, _postgres_url


NATIONAL_SPM = {
    "forecast_content_sha256": "a" * 64,
    "scenario": "baseline",
    "geography_kind": "national",
    "geography_id": None,
    "county_vintage": "2020",
    "as_of": None,
}


def _source_document(marker: str, value: float = 40.0) -> dict:
    document = {
        "people": {
            "adult": {
                "age": {"2026": 40},
                "stage11_marker": {"2026": marker},
                "employment_income": {"2026": value},
            }
        }
    }
    for collection in (
        "households",
        "families",
        "tax_units",
        "spm_units",
        "marital_units",
    ):
        document[collection] = {"group": {"members": ["adult"]}}
    return document


@dataclass
class HouseholdDatabases:
    mysql_sessions: sessionmaker
    postgres_sessions: sessionmaker
    source: HouseholdService
    destination: V2HouseholdService
    marker: str

    def create(self, *, spm=None, value=40.0):
        return self.source.create_household(
            "us",
            _source_document(self.marker, value),
            self.marker,
            spm=spm,
            record_mirror_event=True,
        )

    def mirror(self, creation, *, destination=None, require_pending=False):
        return process_household_event_after_commit(
            "us",
            creation.household.id,
            event_service=self.source,
            mirror_factory=lambda: destination or self.destination,
            require_pending=require_pending,
        )

    def source_receipt(self, creation):
        with self.mysql_sessions() as session:
            source = session.get(V1Household, creation.household.id)
            event = session.get(HouseholdMirrorEvent, creation.mirror_event_id)
            assert source is not None and event is not None
            return {
                "source_id": source.id,
                "household_json": deepcopy(source.household_json),
                "household_hash": source.household_hash,
                "event_id": event.id,
                "payload_json": deepcopy(event.payload_json),
                "fingerprint": event.source_fingerprint_sha256,
            }, event.processed_at


@pytest.fixture
def databases(monkeypatch):
    # Validate both explicit disposable targets before constructing either engine.
    mysql_url, postgres_url = _mysql_url(), _postgres_url()
    mysql_engine = create_engine(mysql_url)
    postgres_engine = create_engine(postgres_url)
    mysql_sessions = sessionmaker(mysql_engine, expire_on_commit=False)
    postgres_sessions = sessionmaker(
        postgres_engine, class_=Session, expire_on_commit=False
    )

    def resolved_selection(country_id, selection):
        assert country_id == "us"
        return deepcopy(NATIONAL_SPM if selection is None else selection)

    monkeypatch.setattr(
        household_service, "normalize_spm_selection", resolved_selection
    )
    marker = f"mysql-household-spm-{uuid4().hex}"
    try:
        yield HouseholdDatabases(
            mysql_sessions,
            postgres_sessions,
            HouseholdService(mysql_sessions),
            V2HouseholdService(HouseholdDatabaseSession(postgres_sessions)),
            marker,
        )
    finally:
        try:
            with mysql_sessions() as session:
                source_ids = list(
                    session.scalars(
                        select(V1Household.id).where(V1Household.label == marker)
                    )
                )
            with postgres_engine.begin() as connection:
                mapping_filter = (
                    LegacyHouseholdMapping.country_id == "us",
                    LegacyHouseholdMapping.legacy_household_id.in_(source_ids),
                )
                destination_ids = list(
                    connection.scalars(
                        select(LegacyHouseholdMapping.household_id).where(
                            *mapping_filter
                        )
                    )
                )
                connection.execute(
                    delete(LegacyHouseholdMapping).where(*mapping_filter)
                )
                connection.execute(
                    delete(Household).where(Household.id.in_(destination_ids))
                )
            with mysql_engine.begin() as connection:
                connection.execute(
                    delete(HouseholdMirrorEvent).where(
                        HouseholdMirrorEvent.legacy_household_id.in_(source_ids),
                        HouseholdMirrorEvent.country_id == "us",
                    )
                )
                connection.execute(
                    delete(V1Household).where(V1Household.id.in_(source_ids))
                )
        finally:
            mysql_engine.dispose()
            postgres_engine.dispose()


@pytest.mark.parametrize("fail_destination", [False, True], ids=["success", "rollback"])
@pytest.mark.parametrize(
    "value",
    [0.04 + 3 / 1_000_000, 0.040940000000000004, -5.684341886080803e-14],
    ids=["float-retry", "stage11-float", "negative-small-float"],
)
def test_spm_source_event_and_postgres_retry_keep_exact_persisted_identity(
    databases, value, fail_destination, record_property
):
    creation = databases.create(value=value, spm=NATIONAL_SPM)
    before, processed_at = databases.source_receipt(creation)
    assert processed_at is None
    assert creation.snapshot is not None
    assert before["household_json"] == creation.snapshot.household_json
    assert before["household_json"]["spm"] == NATIONAL_SPM
    assert before["payload_json"]["snapshot"] == creation.snapshot.model_dump(
        mode="json"
    )
    assert before["fingerprint"] == legacy_household_fingerprint(creation.snapshot)
    with databases.mysql_sessions() as session:
        raw_json = session.execute(
            text("SELECT household_json FROM household WHERE id = :id"),
            {"id": creation.household.id},
        ).scalar_one()
    assert json.loads(raw_json) == before["household_json"]
    stored_value = before["household_json"]["people"]["adult"]["employment_income"][
        "2026"
    ]
    if value == 0.04 + 3 / 1_000_000:
        assert repr(value) == "0.040003000000000004"
        assert stored_value == 0.040003 and stored_value != value
    record_property("input_value", repr(value))
    record_property("mysql_household_json", raw_json)
    record_property("mysql_source_receipt", json.dumps(before, sort_keys=True))

    if fail_destination:

        class FailingTransaction(HouseholdDatabaseSession):
            @contextmanager
            def transaction(self):
                with super().transaction() as session:
                    yield session
                    session.execute(text("SELECT 1 / 0"))

        with pytest.raises(HouseholdMirrorUnavailableError) as failure:
            databases.mirror(
                creation,
                destination=V2HouseholdService(
                    FailingTransaction(databases.postgres_sessions)
                ),
            )
        assert isinstance(failure.value.__cause__, DataError)
        assert databases.source_receipt(creation) == (before, None)
        with databases.postgres_sessions() as session:
            assert (
                session.scalar(
                    select(LegacyHouseholdMapping).where(
                        LegacyHouseholdMapping.country_id == "us",
                        LegacyHouseholdMapping.legacy_household_id
                        == creation.household.id,
                    )
                )
                is None
            )

    first = databases.mirror(creation, require_pending=True)
    replay = databases.mirror(creation)
    assert first.household_created and first.mapping_created
    assert replay.household_id == first.household_id
    assert not replay.household_created and not replay.mapping_created
    after, completed_at = databases.source_receipt(creation)
    assert after == before and completed_at is not None

    # A repeated create is a new immutable legacy source with one shared content row.
    retried_creation = databases.create(value=value, spm=NATIONAL_SPM)
    retried_mirror = databases.mirror(retried_creation)
    assert retried_creation.household.id != creation.household.id
    assert retried_mirror.household_id == first.household_id
    assert not retried_mirror.household_created and retried_mirror.mapping_created
    with databases.postgres_sessions() as session:
        destination = session.get(Household, first.household_id)
        assert destination is not None
        assert destination.household_data["spm"] == NATIONAL_SPM
        assert (
            destination.household_data["people"][0]["values"]["employment_income"][
                "2026"
            ]
            == stored_value
        )
    record_property("postgres_household_id", str(first.household_id))
    record_property("mysql_retry_household_id", retried_creation.household.id)


def test_legacy_absence_and_distinct_spm_selections_keep_distinct_content(databases):
    # Seed an actual pre-SPM legacy source, preserving its absence of a selection.
    with databases.mysql_sessions.begin() as session:
        legacy_json = _source_document(databases.marker)
        legacy = V1Household(
            country_id="us",
            label=databases.marker,
            api_version=COUNTRY_PACKAGE_VERSIONS["us"],
            household_json=legacy_json,
            household_hash=hash_object(legacy_json),
        )
        session.add(legacy)
        session.flush()
        session.refresh(legacy)
        HouseholdService._record_mirror_event(session, legacy)
    legacy_result = process_household_event_after_commit(
        "us",
        legacy.id,
        event_service=databases.source,
        mirror_factory=lambda: databases.destination,
    )
    selections = [
        NATIONAL_SPM,
        {**NATIONAL_SPM, "forecast_content_sha256": "b" * 64},
        {**NATIONAL_SPM, "geography_kind": "county", "geography_id": None},
    ]
    destination_ids = {legacy_result.household_id}
    for selection in selections:
        creation = databases.create(spm=selection)
        result = databases.mirror(creation)
        destination_ids.add(result.household_id)
        with databases.postgres_sessions() as session:
            destination = session.get(Household, result.household_id)
            assert destination is not None
            assert destination.household_data["spm"] == selection
    assert len(destination_ids) == 4
    with databases.postgres_sessions() as session:
        saved_legacy = session.get(Household, legacy_result.household_id)
        assert saved_legacy is not None and "spm" not in saved_legacy.household_data
    saved_source = databases.source.get_household("us", legacy.id)
    assert saved_source is not None and "spm" not in saved_source.household_json


def test_a_creation_that_sends_no_selection_persists_and_mirrors_without_one(
    databases,
):
    """Certifying a bundle must not move an unselected household's stored JSON.

    This fixture resolves an omitted selection to NATIONAL_SPM exactly as a
    certified bundle would. Writing that back would record a choice the caller
    never made, change `household_hash` for identical inputs, and make the
    household's own replay assert a measurement nobody asked for.
    """
    document = _source_document(databases.marker)
    creation = databases.create()
    receipt, _ = databases.source_receipt(creation)

    assert "spm" not in receipt["household_json"]
    assert receipt["household_json"] == document
    assert receipt["household_hash"] == hash_object(document)
    assert creation.snapshot is not None
    assert "spm" not in creation.snapshot.household_json
    assert receipt["fingerprint"] == legacy_household_fingerprint(creation.snapshot)

    result = databases.mirror(creation)
    with databases.postgres_sessions() as session:
        destination = session.get(Household, result.household_id)
        assert destination is not None
        assert "spm" not in destination.household_data
