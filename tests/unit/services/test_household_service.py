import pytest
from sqlalchemy import func, select
from uuid import uuid4

from policyengine_api.data.v1_models import Household, HouseholdMirrorEvent
from policyengine_api.services.household_service import (
    HouseholdMirrorEventIntegrityError,
    HouseholdService,
)
from policyengine_api.services.v2.households.types import (
    LegacyHouseholdPersistenceResult,
)
from tests.fixtures.services.household_fixtures import (
    valid_db_row,
    valid_request_body,
)


pytest_plugins = ["tests.fixtures.services.household_fixtures"]


@pytest.fixture
def service(orm_session_factory):
    return HouseholdService(orm_session_factory)


def test_get_household_returns_mapped_entity(service, existing_household_record):
    household = service.get_household(
        valid_db_row["country_id"],
        valid_db_row["id"],
    )

    assert isinstance(household, Household)
    assert household.household_json == valid_request_body["data"]


def test_get_household_returns_none_for_missing_entity(service):
    assert service.get_household("us", 999) is None


@pytest.mark.parametrize("household_id", ["invalid", -1])
def test_get_household_rejects_invalid_id(service, household_id):
    with pytest.raises(Exception, match="Invalid household ID"):
        service.get_household("us", household_id)


def test_create_household_adds_mapped_entity(service, monkeypatch):
    monkeypatch.setattr(
        "policyengine_api.services.household_service.hash_object",
        lambda value: "some-hash",
    )

    result = service.create_household(
        "us",
        valid_request_body["data"],
        valid_request_body["label"],
    )
    household = result.household

    assert isinstance(household, Household)
    assert household.id is not None
    assert household.household_json == valid_request_body["data"]
    assert result.snapshot is None
    assert result.mirror_event_id is None


def test_household_service_exposes_no_content_update_operation(service) -> None:
    assert not hasattr(service, "update_household")


def test_selected_create_commits_household_and_one_complete_event(
    service,
    orm_session_factory,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "policyengine_api.services.household_service.hash_object",
        lambda value: "source-hash",
    )

    result = service.create_household(
        "us",
        {"people": {"you": {"age": {"2026": 40}}}},
        "Saved name",
        record_mirror_event=True,
    )

    assert result.snapshot is not None
    assert result.mirror_event_id is not None
    assert result.snapshot.legacy_household_id == result.household.id
    assert result.snapshot.label == "Saved name"
    with orm_session_factory() as session:
        event = session.get(HouseholdMirrorEvent, result.mirror_event_id)
        assert event is not None
        assert event.payload_json == {
            "snapshot": result.snapshot.model_dump(mode="json")
        }
        assert event.processed_at is None
        assert event.source_fingerprint_sha256


def test_household_and_event_roll_back_together_when_event_insert_fails(
    orm_session_factory,
    monkeypatch,
) -> None:
    session_type = orm_session_factory.class_
    original_flush = session_type.flush
    flush_count = 0

    def fail_event_flush(session, *args, **kwargs):
        nonlocal flush_count
        flush_count += 1
        original_flush(session, *args, **kwargs)
        if flush_count == 2:
            raise RuntimeError("event insert failed")

    monkeypatch.setattr(session_type, "flush", fail_event_flush)
    service = HouseholdService(orm_session_factory)

    with pytest.raises(Exception, match="Household persistence failed"):
        service.create_household("us", {}, None, record_mirror_event=True)

    monkeypatch.setattr(session_type, "flush", original_flush)
    with orm_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Household)) == 0
        assert (
            session.scalar(select(func.count()).select_from(HouseholdMirrorEvent)) == 0
        )


def test_exact_event_processing_marks_completion_only_after_processor_success(
    service,
    orm_session_factory,
) -> None:
    creation = service.create_household(
        "us",
        {"people": {}},
        None,
        record_mirror_event=True,
    )
    result = LegacyHouseholdPersistenceResult(
        household_id=uuid4(),
        household_created=True,
        mapping_created=True,
    )

    def fail(_event):
        raise RuntimeError("destination unavailable")

    with pytest.raises(RuntimeError, match="destination unavailable"):
        service.process_mirror_event(
            "us",
            creation.household.id,
            processor=fail,
        )
    with orm_session_factory() as session:
        event = session.get(HouseholdMirrorEvent, creation.mirror_event_id)
        assert event is not None
        assert event.processed_at is None

    observed = []
    assert (
        service.process_mirror_event(
            "us",
            creation.household.id,
            processor=lambda event: observed.append(event) or result,
        )
        == result
    )
    with orm_session_factory() as session:
        event = session.get(HouseholdMirrorEvent, creation.mirror_event_id)
        assert event is not None
        assert event.processed_at is not None
        processed_at = event.processed_at

    service.process_mirror_event(
        "us",
        creation.household.id,
        processor=lambda event: observed.append(event) or result,
    )
    assert observed[0].was_processed is False
    assert observed[1].was_processed is True
    with orm_session_factory() as session:
        event = session.get(HouseholdMirrorEvent, creation.mirror_event_id)
        assert event is not None
        assert event.processed_at == processed_at


def test_event_payload_or_fingerprint_conflict_fails_without_completion(
    service,
    orm_session_factory,
) -> None:
    creation = service.create_household(
        "us",
        {"people": {}},
        None,
        record_mirror_event=True,
    )
    with orm_session_factory.begin() as session:
        event = session.get(HouseholdMirrorEvent, creation.mirror_event_id)
        assert event is not None
        event.source_fingerprint_sha256 = "f" * 64

    with pytest.raises(HouseholdMirrorEventIntegrityError, match="fingerprint"):
        service.process_mirror_event(
            "us",
            creation.household.id,
            processor=lambda _event: None,
        )
    with orm_session_factory() as session:
        event = session.get(HouseholdMirrorEvent, creation.mirror_event_id)
        assert event is not None
        assert event.processed_at is None
