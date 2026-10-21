"""Pin the statement that maps a copied v1 household to its v2 household."""

from __future__ import annotations

from collections import deque
from types import SimpleNamespace
from uuid import UUID

import pytest

from policyengine_api.data.v2.models import LegacyHouseholdMapping
from policyengine_api.services.v2.households import services
from policyengine_api.services.v2.households.database_connectors import creates
from policyengine_api.services.v2.households.transformations import (
    legacy_household_fingerprint,
)
from policyengine_api.services.v2.households.types import LegacyHouseholdSnapshot
from policyengine_api.services.v2.households.validators import (
    LegacyHouseholdMappingIntegrityError,
)
from tests.fixtures.recording_session import RecordingSession

HOUSEHOLD_ID = UUID("00000000-0000-0000-0000-000000000042")
MAPPING_ID = UUID("00000000-0000-0000-0000-000000000099")
INSERT_MAPPING = (
    "INSERT INTO legacy_household_mappings (id, created_at, updated_at, "
    "country_id, legacy_household_id, household_id, source_api_version, "
    "fingerprint_version, fingerprint_sha256) VALUES (%(id)s::UUID, "
    "%(created_at)s::TIMESTAMP WITH TIME ZONE, "
    "%(updated_at)s::TIMESTAMP WITH TIME ZONE, %(country_id)s::VARCHAR, "
    "%(legacy_household_id)s::BIGINT, %(household_id)s::UUID, "
    "%(source_api_version)s::VARCHAR, %(fingerprint_version)s::INTEGER, "
    "%(fingerprint_sha256)s::VARCHAR) ON CONFLICT ON CONSTRAINT "
    "uq_legacy_household_mappings_country_legacy DO NOTHING RETURNING "
    "legacy_household_mappings.id"
)


def _snapshot() -> LegacyHouseholdSnapshot:
    return LegacyHouseholdSnapshot(
        country_id="uk",
        legacy_household_id=42,
        api_version="2.3.4",
        household_json={"people": {}},
        source_household_hash="source-hash",
    )


@pytest.fixture(autouse=True)
def stored_household(monkeypatch) -> None:
    monkeypatch.setattr(creates, "uuid4", lambda: MAPPING_ID)
    monkeypatch.setattr(
        services,
        "create_normalized_household",
        lambda _session, _household_input: SimpleNamespace(
            household_id=HOUSEHOLD_ID, created=True
        ),
    )


def _mapping_insert() -> tuple:
    return (
        "execute",
        INSERT_MAPPING,
        {
            "id": MAPPING_ID,
            "created_at": None,
            "updated_at": None,
            "country_id": "uk",
            "legacy_household_id": 42,
            "household_id": HOUSEHOLD_ID,
            "source_api_version": "2.3.4",
            "fingerprint_version": 1,
            "fingerprint_sha256": legacy_household_fingerprint(_snapshot()),
        },
    )


def test_first_copy_inserts_its_mapping_with_the_snapshot_provenance() -> None:
    session = RecordingSession(results=deque([None, MAPPING_ID]))

    result = services.mirror_legacy_household_in_session(session, _snapshot())

    assert session.operations[1] == _mapping_insert()
    assert len(session.operations) == 2
    assert result == services.LegacyHouseholdPersistenceResult(
        household_id=HOUSEHOLD_ID,
        household_created=True,
        mapping_created=True,
    )


def test_lost_mapping_race_verifies_and_reuses_the_stored_mapping() -> None:
    winner = LegacyHouseholdMapping(
        country_id="uk",
        legacy_household_id=42,
        household_id=HOUSEHOLD_ID,
        source_api_version="2.3.4",
        fingerprint_version=1,
        fingerprint_sha256=legacy_household_fingerprint(_snapshot()),
    )
    session = RecordingSession(results=deque([None, None, winner]))

    result = services.mirror_legacy_household_in_session(session, _snapshot())

    assert session.operations[1] == _mapping_insert()
    assert len(session.operations) == 3
    assert result == services.LegacyHouseholdPersistenceResult(
        household_id=HOUSEHOLD_ID,
        household_created=False,
        mapping_created=False,
    )


def test_lost_mapping_race_without_a_stored_winner_is_an_integrity_error() -> None:
    session = RecordingSession(results=deque([None, None, None]))

    with pytest.raises(
        LegacyHouseholdMappingIntegrityError,
        match=r"^legacy household mapping conflict did not resolve to a stored row$",
    ):
        services.mirror_legacy_household_in_session(session, _snapshot())

    assert session.operations[1] == _mapping_insert()
