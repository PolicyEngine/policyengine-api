"""Immediate v1 household create-event copying and observability tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from sqlalchemy.exc import OperationalError

from policyengine_api.services.household_mirroring import (
    HouseholdMirrorUnavailableError,
    process_household_event_after_commit,
)
from policyengine_api.services.household_service import PendingHouseholdMirrorEvent
from policyengine_api.services.v2.households.types import (
    LegacyHouseholdPersistenceResult,
    LegacyHouseholdSnapshot,
)
from policyengine_api.services.v2.households.validators import (
    LegacyHouseholdTranslationError,
)


HOUSEHOLD_ID = UUID("00000000-0000-0000-0000-000000000010")


def _snapshot() -> LegacyHouseholdSnapshot:
    return LegacyHouseholdSnapshot(
        country_id="us",
        legacy_household_id=42,
        label="Private saved name",
        api_version="1.0.0",
        household_json={"people": {"you": {"income": {"2026": 12345}}}},
        source_household_hash="private-source-hash",
    )


def _result() -> LegacyHouseholdPersistenceResult:
    return LegacyHouseholdPersistenceResult(
        household_id=HOUSEHOLD_ID,
        household_created=True,
        mapping_created=True,
    )


def _event_service(*, fail_after_destination: bool = False):
    service = MagicMock()

    def process(
        country_id,
        legacy_household_id,
        *,
        processor,
        after_processed_commit,
        require_pending,
    ):
        assert (country_id, legacy_household_id) == ("us", 42)
        assert require_pending is False
        event = PendingHouseholdMirrorEvent(
            event_id=7,
            snapshot=_snapshot(),
            source_fingerprint_sha256="f" * 64,
            was_processed=False,
        )
        result = processor(event)
        if fail_after_destination:
            raise OperationalError("update secret", {}, Exception("credential"))
        after_processed_commit(event, result)
        return result

    service.process_mirror_event.side_effect = process
    return service


def test_success_records_destination_and_no_household_values() -> None:
    mirror = MagicMock()
    mirror.mirror_legacy_household.return_value = _result()
    event_service = _event_service()

    with patch("policyengine_api.services.household_mirroring.logger") as logger:
        result = process_household_event_after_commit(
            "us",
            42,
            event_service=event_service,
            mirror_factory=lambda: mirror,
        )

    assert result.household_id == HOUSEHOLD_ID
    payload = logger.log_struct.call_args.args[0]
    assert payload["metric_name"] == "v1_household_mirror_operations"
    assert payload["actual_write_sources"] == ["cloud_sql", "supabase"]
    assert payload["destination_household_id"] == str(HOUSEHOLD_ID)
    assert payload["pending_event"] is False
    assert "12345" not in repr(payload)
    assert "Private saved name" not in repr(payload)
    assert "private-source-hash" not in repr(payload)


def test_logging_failure_does_not_change_successful_copy_result() -> None:
    mirror = MagicMock()
    mirror.mirror_legacy_household.return_value = _result()

    with patch(
        "policyengine_api.services.household_mirroring.logger.log_struct",
        side_effect=RuntimeError("logging unavailable"),
    ):
        result = process_household_event_after_commit(
            "us",
            42,
            event_service=_event_service(),
            mirror_factory=lambda: mirror,
        )

    assert result == _result()


def test_logging_failure_does_not_mask_copy_failure() -> None:
    copy_error = OperationalError("copy unavailable", {}, Exception("database"))
    mirror = MagicMock()
    mirror.mirror_legacy_household.side_effect = copy_error

    with (
        patch(
            "policyengine_api.services.household_mirroring.logger.log_struct",
            side_effect=RuntimeError("logging unavailable"),
        ),
        pytest.raises(HouseholdMirrorUnavailableError) as raised,
    ):
        process_household_event_after_commit(
            "us",
            42,
            event_service=_event_service(),
            mirror_factory=lambda: mirror,
        )

    assert raised.value.__cause__ is copy_error


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (LegacyHouseholdTranslationError("private value"), "translation"),
        (
            OperationalError("statement secret", {}, Exception("credential")),
            "database",
        ),
        (RuntimeError("household content secret"), "unexpected"),
    ],
)
def test_destination_failure_is_secret_safe_and_leaves_event_pending(
    error: Exception,
    category: str,
) -> None:
    mirror = MagicMock()
    mirror.mirror_legacy_household.side_effect = error

    with (
        patch("policyengine_api.services.household_mirroring.logger") as logger,
        pytest.raises(HouseholdMirrorUnavailableError, match="could not be copied"),
    ):
        process_household_event_after_commit(
            "us",
            42,
            event_service=_event_service(),
            mirror_factory=lambda: mirror,
        )

    payload = logger.log_struct.call_args.args[0]
    assert payload["failure_category"] == category
    assert payload["actual_write_sources"] == ["cloud_sql"]
    assert payload["pending_event"] is True
    assert "secret" not in repr(payload)
    assert "credential" not in repr(payload)
    assert "private value" not in repr(payload)


def test_source_completion_failure_records_committed_destination_and_pending_event() -> (
    None
):
    mirror = MagicMock()
    mirror.mirror_legacy_household.return_value = _result()

    with (
        patch("policyengine_api.services.household_mirroring.logger") as logger,
        pytest.raises(HouseholdMirrorUnavailableError),
    ):
        process_household_event_after_commit(
            "us",
            42,
            event_service=_event_service(fail_after_destination=True),
            mirror_factory=lambda: mirror,
        )

    payload = logger.log_struct.call_args.args[0]
    assert payload["actual_write_sources"] == ["cloud_sql", "supabase"]
    assert payload["destination_household_id"] == str(HOUSEHOLD_ID)
    assert payload["pending_event"] is True
