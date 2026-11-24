"""Cross-database tests for retained v1 household create-event copying."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import OperationalError

from policyengine_api.data.v1_models import (
    Household as V1Household,
)
from policyengine_api.data.v1_models import (
    HouseholdMirrorEvent,
)
from policyengine_api.data.v2.models import Household, LegacyHouseholdMapping
from policyengine_api.services.household_mirroring import (
    HouseholdMirrorUnavailableError,
    process_household_event_after_commit,
)
from policyengine_api.services.household_service import (
    HouseholdPersistenceError,
    HouseholdService,
)
from policyengine_api.services.v2.households.database_session import (
    HouseholdDatabaseSession,
)
from policyengine_api.services.v2.households.services import (
    V2HouseholdService,
    mirror_legacy_household_in_session,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as OrmSession
    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session


def _v1_service(v1_sessions: sessionmaker[OrmSession]) -> HouseholdService:
    _cleanup_v1(v1_sessions)
    return HouseholdService(v1_sessions)


def _cleanup_v1(v1_sessions: sessionmaker[OrmSession]) -> None:
    with v1_sessions.begin() as session:
        session.execute(delete(HouseholdMirrorEvent))
        session.execute(delete(V1Household))


def _source_document() -> dict[str, object]:
    people = {"adult": {"age": {"2026": 40}}}
    members = {"members": ["adult"]}
    return {
        "people": people,
        "households": {"home": members},
        "families": {"family": members},
        "tax_units": {"tax unit": members},
        "spm_units": {"spm unit": members},
        "marital_units": {"marital unit": members},
    }


def _create_v1(service: HouseholdService):
    return service.create_household(
        "us",
        _source_document(),
        "Cross-database household",
        record_mirror_event=True,
    )


def _cleanup_v2(v2_owner_sessions: sessionmaker[Session]) -> None:
    with v2_owner_sessions.begin() as session:
        session.execute(delete(LegacyHouseholdMapping))
        session.execute(delete(Household))


def test_both_commits_and_client_retry_create_distinct_sources_one_content_row(
    v1_sessions: sessionmaker[OrmSession],
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    v1_service = _v1_service(v1_sessions)
    try:
        mirror_service = V2HouseholdService(HouseholdDatabaseSession(v2_owner_sessions))
        first = _create_v1(v1_service)
        first_result = process_household_event_after_commit(
            "us",
            first.household.id,
            event_service=v1_service,
            mirror_factory=lambda: mirror_service,
        )
        retry = _create_v1(v1_service)
        retry_result = process_household_event_after_commit(
            "us",
            retry.household.id,
            event_service=v1_service,
            mirror_factory=lambda: mirror_service,
        )

        assert first.household.id != retry.household.id
        assert first_result.household_id == retry_result.household_id
        with v1_sessions() as session:
            assert session.scalar(select(func.count()).select_from(V1Household)) == 2
            assert (
                session.scalar(select(func.count()).select_from(HouseholdMirrorEvent))
                == 2
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(HouseholdMirrorEvent)
                    .where(HouseholdMirrorEvent.processed_at.is_not(None))
                )
                == 2
            )
        with v2_owner_sessions() as session:
            assert session.scalar(select(func.count()).select_from(Household)) == 1
            assert (
                session.scalar(select(func.count()).select_from(LegacyHouseholdMapping))
                == 2
            )
    finally:
        _cleanup_v2(v2_owner_sessions)
        _cleanup_v1(v1_sessions)


def test_destination_failure_leaves_source_and_event_pending_for_exact_replay(
    v1_sessions: sessionmaker[OrmSession],
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    v1_service = _v1_service(v1_sessions)
    try:
        creation = _create_v1(v1_service)

        class FailingMirror:
            def mirror_legacy_household(self, snapshot):
                with v2_owner_sessions.begin() as session:
                    mirror_legacy_household_in_session(session, snapshot)
                    msg = "forced transaction failure"
                    raise OperationalError(
                        msg,
                        {},
                        RuntimeError("forced"),
                    )

        with pytest.raises(HouseholdMirrorUnavailableError):
            process_household_event_after_commit(
                "us",
                creation.household.id,
                event_service=v1_service,
                mirror_factory=FailingMirror,
            )

        with v1_sessions() as session:
            event = session.get(HouseholdMirrorEvent, creation.mirror_event_id)
            assert event is not None
            assert event.processed_at is None
            assert session.get(V1Household, creation.household.id) is not None
        with v2_owner_sessions() as session:
            assert session.scalar(select(func.count()).select_from(Household)) == 0

        replay = process_household_event_after_commit(
            "us",
            creation.household.id,
            event_service=v1_service,
            mirror_factory=lambda: V2HouseholdService(
                HouseholdDatabaseSession(v2_owner_sessions)
            ),
            require_pending=True,
        )
        assert replay.mapping_created is True
    finally:
        _cleanup_v2(v2_owner_sessions)
        _cleanup_v1(v1_sessions)


def test_replay_after_destination_commit_verifies_mapping_then_completes_event(
    v1_sessions: sessionmaker[OrmSession],
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    v1_service = _v1_service(v1_sessions)
    try:
        creation = _create_v1(v1_service)
        assert creation.snapshot is not None
        mirror_service = V2HouseholdService(HouseholdDatabaseSession(v2_owner_sessions))

        committed = mirror_service.mirror_legacy_household(creation.snapshot)
        with v1_sessions() as session:
            event = session.get(HouseholdMirrorEvent, creation.mirror_event_id)
            assert event is not None
            assert event.processed_at is None

        replay = process_household_event_after_commit(
            "us",
            creation.household.id,
            event_service=v1_service,
            mirror_factory=lambda: mirror_service,
            require_pending=True,
        )

        assert replay.household_id == committed.household_id
        assert replay.household_created is False
        assert replay.mapping_created is False
        with v1_sessions() as session:
            event = session.get(HouseholdMirrorEvent, creation.mirror_event_id)
            assert event is not None
            assert event.processed_at is not None
    finally:
        _cleanup_v2(v2_owner_sessions)
        _cleanup_v1(v1_sessions)


def test_source_event_failure_rolls_back_the_source_household(
    v1_sessions: sessionmaker[OrmSession],
) -> None:
    v1_service = _v1_service(v1_sessions)
    try:
        with (
            patch.object(
                HouseholdService,
                "_record_mirror_event",
                side_effect=RuntimeError("forced event failure"),
            ),
            pytest.raises(HouseholdPersistenceError),
        ):
            _create_v1(v1_service)

        with v1_sessions() as session:
            assert session.scalar(select(func.count()).select_from(V1Household)) == 0
            assert (
                session.scalar(select(func.count()).select_from(HouseholdMirrorEvent))
                == 0
            )
    finally:
        _cleanup_v1(v1_sessions)


def test_translation_failure_retains_one_pending_event_until_explicit_replay(
    v1_sessions: sessionmaker[OrmSession],
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    v1_service = _v1_service(v1_sessions)
    try:
        creation = v1_service.create_household(
            "us",
            {"people": {"adult": {"age": {"2026": 40}}}},
            "Structurally incomplete household",
            record_mirror_event=True,
        )
        with pytest.raises(HouseholdMirrorUnavailableError):
            process_household_event_after_commit(
                "us",
                creation.household.id,
                event_service=v1_service,
                mirror_factory=lambda: V2HouseholdService(
                    HouseholdDatabaseSession(v2_owner_sessions)
                ),
            )

        with v1_sessions() as session:
            event = session.get(HouseholdMirrorEvent, creation.mirror_event_id)
            assert event is not None
            assert event.processed_at is None
        with v2_owner_sessions() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(LegacyHouseholdMapping)
                    .where(
                        LegacyHouseholdMapping.country_id == "us",
                        LegacyHouseholdMapping.legacy_household_id
                        == creation.household.id,
                    )
                )
                == 0
            )
    finally:
        _cleanup_v2(v2_owner_sessions)
        _cleanup_v1(v1_sessions)


def test_changed_retained_event_fingerprint_cannot_mutate_destination(
    v1_sessions: sessionmaker[OrmSession],
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    v1_service = _v1_service(v1_sessions)
    try:
        creation = _create_v1(v1_service)
        mirror_service = V2HouseholdService(HouseholdDatabaseSession(v2_owner_sessions))
        committed = process_household_event_after_commit(
            "us",
            creation.household.id,
            event_service=v1_service,
            mirror_factory=lambda: mirror_service,
        )
        with v1_sessions.begin() as session:
            event = session.get(HouseholdMirrorEvent, creation.mirror_event_id)
            assert event is not None
            changed_payload = dict(event.payload_json)
            changed_snapshot = dict(changed_payload["snapshot"])
            changed_snapshot["label"] = "Changed after commit"
            event.payload_json = {"snapshot": changed_snapshot}
            session.add(event)

        with pytest.raises(HouseholdMirrorUnavailableError):
            process_household_event_after_commit(
                "us",
                creation.household.id,
                event_service=v1_service,
                mirror_factory=lambda: mirror_service,
            )

        with v2_owner_sessions() as session:
            mappings = session.scalars(
                select(LegacyHouseholdMapping).where(
                    LegacyHouseholdMapping.country_id == "us",
                    LegacyHouseholdMapping.legacy_household_id == creation.household.id,
                )
            ).all()
            assert len(mappings) == 1
            assert mappings[0].household_id == committed.household_id
    finally:
        _cleanup_v2(v2_owner_sessions)
        _cleanup_v1(v1_sessions)


@pytest.mark.parametrize("country_id", ["us", "uk"])
def test_cloud_sql_only_writes_create_no_event_or_destination_mapping(
    country_id: str,
    v1_sessions: sessionmaker[OrmSession],
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    v1_service = _v1_service(v1_sessions)
    try:
        creation = v1_service.create_household(
            country_id,
            {"people": {"adult": {}}},
            "Cloud SQL only",
            record_mirror_event=False,
        )
        assert creation.snapshot is None
        assert creation.mirror_event_id is None
        with v1_sessions() as session:
            assert session.scalar(select(func.count()).select_from(V1Household)) == 1
            assert (
                session.scalar(select(func.count()).select_from(HouseholdMirrorEvent))
                == 0
            )
        with v2_owner_sessions() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(LegacyHouseholdMapping)
                    .where(
                        LegacyHouseholdMapping.country_id == country_id,
                        LegacyHouseholdMapping.legacy_household_id
                        == creation.household.id,
                    )
                )
                == 0
            )
    finally:
        _cleanup_v2(v2_owner_sessions)
        _cleanup_v1(v1_sessions)
