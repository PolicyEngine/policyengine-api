"""Pin the complete metric log record of every immediate v1-to-v2 mirror outcome."""

from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from sqlalchemy.exc import OperationalError

from policyengine_api.services.household_mirroring import (
    HouseholdMirrorUnavailableError,
    process_household_event_after_commit,
)
from policyengine_api.services.household_service import PendingHouseholdMirrorEvent
from policyengine_api.services.policy_mirroring import (
    PolicyMirrorUnavailableError,
    mirror_policy_after_commit,
)
from policyengine_api.services.user_policy_mirroring import (
    UserPolicyMirrorCollaborators,
    UserPolicyMirrorUnavailableError,
    mirror_pending_user_policy_events_after_commit,
    mirror_user_policy_after_commit,
)
from policyengine_api.services.user_policy_service import PendingUserPolicyMirrorEvent
from policyengine_api.services.v2.households.types import (
    LegacyHouseholdPersistenceResult,
    LegacyHouseholdSnapshot,
)
from policyengine_api.services.v2.policies.types import (
    LegacyPolicyPersistenceResult,
    LegacyPolicySnapshot,
)
from policyengine_api.services.v2.user_policies.types import (
    LegacyUserPolicyPersistenceResult,
    LegacyUserPolicySnapshot,
)

DESTINATION_ID = UUID("00000000-0000-0000-0000-000000000010")
ASSOCIATION_ID = UUID("00000000-0000-0000-0000-000000000060")
DATABASE_ERROR = OperationalError("statement", {}, Exception("database"))


def _logged(logger: MagicMock) -> tuple[dict[str, object], str]:
    """Return the one logged record without its timing, and its severity."""
    logger.log_struct.assert_called_once()
    payload = dict(logger.log_struct.call_args.args[0])
    assert isinstance(payload.pop("duration_ms"), float)
    return payload, logger.log_struct.call_args.kwargs["severity"]


def _household_snapshot() -> LegacyHouseholdSnapshot:
    return LegacyHouseholdSnapshot(
        country_id="us",
        legacy_household_id=42,
        api_version="1.0.0",
        household_json={"people": {}},
        source_household_hash="source-hash",
    )


def _household_event_service(*, fail_after_destination: bool) -> MagicMock:
    service = MagicMock()

    def process(_country_id, _legacy_household_id, **callbacks):
        event = PendingHouseholdMirrorEvent(
            event_id=7,
            snapshot=_household_snapshot(),
            source_fingerprint_sha256="f" * 64,
            was_processed=False,
        )
        result = callbacks["processor"](event)
        if fail_after_destination:
            raise DATABASE_ERROR
        callbacks["after_processed_commit"](event, result)
        return result

    service.process_mirror_event.side_effect = process
    return service


def _household_record(**changes: object) -> dict[str, object]:
    record: dict[str, object] = {
        "message": "V1 household immediate copy completed",
        "metric_name": "v1_household_mirror_operations",
        "metric_value": 1,
        "configured_write_source": "dual_write",
        "attempted_write_sources": ["cloud_sql", "supabase"],
        "actual_write_sources": ["cloud_sql", "supabase"],
        "country_id": "us",
        "legacy_household_id": 42,
        "destination_household_id": str(DESTINATION_ID),
        "outcome": "ok",
        "failure_category": None,
        "household_created": True,
        "mapping_created": False,
        "pending_event": False,
    }
    record.update(changes)
    return record


@pytest.mark.parametrize(
    ("failing_write", "expected", "severity"),
    [
        (None, _household_record(), "INFO"),
        (
            "source",
            _household_record(
                outcome="error", failure_category="database", pending_event=True
            ),
            "ERROR",
        ),
        (
            "destination",
            _household_record(
                actual_write_sources=["cloud_sql"],
                destination_household_id=None,
                outcome="error",
                failure_category="database",
                household_created=None,
                mapping_created=None,
                pending_event=True,
            ),
            "ERROR",
        ),
    ],
)
def test_household_copy_logs_one_complete_record(
    failing_write: str | None,
    expected: dict[str, object],
    severity: str,
) -> None:
    mirror = MagicMock()
    if failing_write == "destination":
        mirror.mirror_legacy_household.side_effect = DATABASE_ERROR
    else:
        mirror.mirror_legacy_household.return_value = LegacyHouseholdPersistenceResult(
            household_id=DESTINATION_ID,
            household_created=True,
            mapping_created=False,
        )

    expected_failure = (
        nullcontext()
        if failing_write is None
        else pytest.raises(HouseholdMirrorUnavailableError)
    )
    with (
        patch("policyengine_api.services.household_mirroring.logger") as logger,
        expected_failure as raised,
    ):
        process_household_event_after_commit(
            "us",
            42,
            event_service=_household_event_service(
                fail_after_destination=failing_write == "source"
            ),
            mirror_factory=lambda: mirror,
        )

    if failing_write is not None:
        assert raised.value.__cause__ is DATABASE_ERROR

    payload, logged_severity = _logged(logger)
    assert list(payload) == list(expected)
    assert payload == expected
    assert logged_severity == severity


def _policy_snapshot() -> LegacyPolicySnapshot:
    return LegacyPolicySnapshot(
        country_id="uk",
        legacy_policy_id=5,
        api_version="1.0.0",
        policy_json={},
        source_policy_hash="legacy-hash",
    )


def test_policy_mirror_success_logs_one_complete_record() -> None:
    mirror = MagicMock()
    mirror.mirror_legacy_policy.return_value = LegacyPolicyPersistenceResult(
        policy_id=DESTINATION_ID,
        policy_created=False,
        mapping_created=True,
    )

    with patch("policyengine_api.services.policy_mirroring.logger") as logger:
        mirror_policy_after_commit(_policy_snapshot(), mirror_factory=lambda: mirror)

    payload, severity = _logged(logger)
    expected = {
        "message": "V1 policy immediate mirror completed",
        "metric_name": "v1_policy_mirror_operations",
        "metric_value": 1,
        "configured_write_source": "dual_write",
        "attempted_write_sources": ["cloud_sql", "supabase"],
        "actual_write_sources": ["cloud_sql", "supabase"],
        "country_id": "uk",
        "legacy_policy_id": 5,
        "destination_policy_id": str(DESTINATION_ID),
        "outcome": "ok",
        "failure_category": None,
        "failure_reason": None,
        "policy_created": False,
        "mapping_created": True,
    }
    assert list(payload) == list(expected)
    assert payload == expected
    assert severity == "INFO"


def test_policy_mirror_failure_logs_one_complete_record() -> None:
    mirror = MagicMock()
    mirror.mirror_legacy_policy.side_effect = DATABASE_ERROR

    with (
        patch("policyengine_api.services.policy_mirroring.logger") as logger,
        pytest.raises(PolicyMirrorUnavailableError),
    ):
        mirror_policy_after_commit(_policy_snapshot(), mirror_factory=lambda: mirror)

    payload, severity = _logged(logger)
    expected = {
        "message": "V1 policy immediate mirror completed",
        "metric_name": "v1_policy_mirror_operations",
        "metric_value": 1,
        "configured_write_source": "dual_write",
        "attempted_write_sources": ["cloud_sql", "supabase"],
        "actual_write_sources": ["cloud_sql"],
        "country_id": "uk",
        "legacy_policy_id": 5,
        "destination_policy_id": None,
        "outcome": "error",
        "failure_category": "database",
        "failure_reason": "database_error",
        "policy_created": None,
        "mapping_created": None,
    }
    assert list(payload) == list(expected)
    assert payload == expected
    assert severity == "ERROR"


def _saved_snapshot(legacy_user_policy_id: int = 10) -> LegacyUserPolicySnapshot:
    return LegacyUserPolicySnapshot(
        country_id="us",
        legacy_user_policy_id=legacy_user_policy_id,
        reform_id=2,
        baseline_id=1,
        user_id="auth0|one",
        year="2026",
        geography="us",
        number_of_provisions=3,
        api_version="1.0.0",
        added_date=1,
        updated_date=2,
    )


def _user_policy_result() -> LegacyUserPolicyPersistenceResult:
    return LegacyUserPolicyPersistenceResult(
        association_id=ASSOCIATION_ID,
        policy_id=DESTINATION_ID,
        association_created=False,
        association_updated=True,
        mapping_created=False,
    )


def _user_policy_record(**changes: object) -> dict[str, object]:
    record: dict[str, object] = {
        "message": "V1 saved-policy immediate mirror completed",
        "metric_name": "v1_user_policy_mirror_operations",
        "metric_value": 1,
        "configured_write_source": "dual_write",
        "attempted_write_sources": ["cloud_sql", "supabase"],
        "actual_write_sources": ["cloud_sql", "supabase"],
        "country_id": "us",
        "legacy_user_policy_id": 10,
        "source_revision": 3,
        "requested_through_revision": 3,
        "destination_association_id": str(ASSOCIATION_ID),
        "destination_policy_id": str(DESTINATION_ID),
        "outcome": "ok",
        "failure_category": None,
        "failure_reason": None,
        "association_created": False,
        "association_updated": True,
        "mapping_created": False,
    }
    record.update(changes)
    return record


FAILED_USER_POLICY_RECORD = _user_policy_record(
    actual_write_sources=["cloud_sql"],
    destination_association_id=None,
    destination_policy_id=None,
    outcome="error",
    failure_category="database",
    failure_reason="database_error",
    association_created=None,
    association_updated=None,
    mapping_created=None,
)


@pytest.mark.parametrize("fails", [False, True])
def test_single_saved_policy_mirror_logs_one_complete_record(fails) -> None:
    mirror = MagicMock()
    if fails:
        mirror.mirror_legacy_user_policy.side_effect = DATABASE_ERROR
    else:
        mirror.mirror_legacy_user_policy.return_value = _user_policy_result()

    expected_failure = (
        pytest.raises(UserPolicyMirrorUnavailableError) if fails else nullcontext()
    )
    with (
        patch("policyengine_api.services.user_policy_mirroring.logger") as logger,
        expected_failure as raised,
    ):
        mirror_user_policy_after_commit(
            _saved_snapshot(),
            _policy_snapshot(),
            source_revision=3,
            mirror_factory=lambda: mirror,
        )

    if fails:
        assert raised.value.__cause__ is DATABASE_ERROR

    payload, severity = _logged(logger)
    expected = FAILED_USER_POLICY_RECORD if fails else _user_policy_record()
    assert list(payload) == list(expected)
    assert payload == expected
    assert severity == ("ERROR" if fails else "INFO")


def _pending_event(source_revision: int) -> PendingUserPolicyMirrorEvent:
    return PendingUserPolicyMirrorEvent(
        event_id=source_revision,
        source_revision=source_revision,
        event_type="update",
        snapshot=_saved_snapshot(legacy_user_policy_id=11),
        changed_fields=frozenset({"reform_label"}),
        source_fingerprint_sha256="f" * 64,
    )


def _pending_event_service(*, failure: Exception | None) -> MagicMock:
    service = MagicMock()

    def process(_country_id, _legacy_user_policy_id, *, through_revision, **callbacks):
        result = None
        for revision in (2, through_revision):
            event = _pending_event(revision)
            result = callbacks["processor"](event)
            if failure is not None and revision == through_revision:
                raise failure
            callbacks["after_processed_commit"](event, result)
        return result

    service.process_pending_mirror_events.side_effect = process
    return service


def test_pending_saved_policy_events_log_one_complete_record_each() -> None:
    mirror = MagicMock()
    mirror.mirror_legacy_user_policy.return_value = _user_policy_result()

    with patch("policyengine_api.services.user_policy_mirroring.logger") as logger:
        result = mirror_pending_user_policy_events_after_commit(
            "us",
            11,
            through_revision=3,
            collaborators=UserPolicyMirrorCollaborators(
                event_service=_pending_event_service(failure=None),
                reform_snapshot_loader=lambda _country_id, _policy_id: (
                    _policy_snapshot()
                ),
                mirror_factory=lambda: mirror,
            ),
        )

    assert result == _user_policy_result()
    records = []
    for call in logger.log_struct.call_args_list:
        payload = dict(call.args[0])
        assert isinstance(payload.pop("duration_ms"), float)
        records.append((payload, call.kwargs["severity"]))
    assert records == [
        (
            _user_policy_record(legacy_user_policy_id=11, source_revision=2),
            "INFO",
        ),
        (_user_policy_record(legacy_user_policy_id=11), "INFO"),
    ]
    assert list(records[0][0]) == list(_user_policy_record())


def test_pending_event_failure_logs_the_active_event_and_unwrapped_cause() -> None:
    mirror = MagicMock()
    mirror.mirror_legacy_user_policy.return_value = _user_policy_result()
    wrapped = UserPolicyMirrorUnavailableError("wrapped")
    wrapped.__cause__ = DATABASE_ERROR

    with (
        patch("policyengine_api.services.user_policy_mirroring.logger") as logger,
        pytest.raises(UserPolicyMirrorUnavailableError) as raised,
    ):
        mirror_pending_user_policy_events_after_commit(
            "us",
            11,
            through_revision=3,
            collaborators=UserPolicyMirrorCollaborators(
                event_service=_pending_event_service(failure=wrapped),
                reform_snapshot_loader=lambda _country_id, _policy_id: (
                    _policy_snapshot()
                ),
                mirror_factory=lambda: mirror,
            ),
        )

    assert raised.value.__cause__ is wrapped
    payload = dict(logger.log_struct.call_args_list[-1].args[0])
    assert isinstance(payload.pop("duration_ms"), float)
    expected = _user_policy_record(
        legacy_user_policy_id=11,
        outcome="error",
        failure_category="database",
        failure_reason="database_error",
    )
    assert list(payload) == list(expected)
    assert payload == expected
    assert logger.log_struct.call_args_list[-1].kwargs["severity"] == "ERROR"


def test_pending_event_failure_before_any_event_logs_the_request_identity() -> None:
    event_service = MagicMock()
    event_service.process_pending_mirror_events.side_effect = DATABASE_ERROR

    with (
        patch("policyengine_api.services.user_policy_mirroring.logger") as logger,
        pytest.raises(UserPolicyMirrorUnavailableError),
    ):
        mirror_pending_user_policy_events_after_commit(
            "uk",
            12,
            through_revision=4,
            collaborators=UserPolicyMirrorCollaborators(
                event_service=event_service,
                reform_snapshot_loader=lambda _country_id, _policy_id: None,
                mirror_factory=MagicMock(),
            ),
        )

    payload, severity = _logged(logger)
    expected = {
        **FAILED_USER_POLICY_RECORD,
        "country_id": "uk",
        "legacy_user_policy_id": 12,
        "source_revision": None,
        "requested_through_revision": 4,
    }
    assert list(payload) == list(_user_policy_record())
    assert payload == expected
    assert severity == "ERROR"
