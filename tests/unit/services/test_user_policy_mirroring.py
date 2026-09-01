"""Saved-policy mirror observability and error conversion tests."""

from __future__ import annotations

from uuid import UUID
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import event as sqlalchemy_event, select
from sqlalchemy.exc import OperationalError, TimeoutError

from policyengine_api.data.v1_models import UserPolicyMirrorEvent
from policyengine_api.data.v2.user_policies.legacy_mapping_repository import (
    LegacyUserPolicyIntegrityError,
    LegacyUserPolicyPersistenceResult,
)
from policyengine_api.services.v2.policies.legacy_translation import (
    LegacyPolicySnapshot,
)
from policyengine_api.services.v2.user_policies.legacy_translation import (
    LegacyUserPolicySnapshot,
)
from policyengine_api.services.user_policy_mirroring import (
    UserPolicyMirrorUnavailableError,
    mirror_pending_user_policy_events_after_commit,
    mirror_user_policy_after_commit,
)
from policyengine_api.services.user_policy_service import UserPolicyService


ASSOCIATION_ID = UUID("00000000-0000-0000-0000-000000000060")
POLICY_ID = UUID("00000000-0000-0000-0000-000000000010")


def _saved() -> LegacyUserPolicySnapshot:
    return LegacyUserPolicySnapshot(
        country_id="us",
        legacy_user_policy_id=10,
        reform_id=2,
        reform_label="Reform",
        baseline_id=1,
        baseline_label="Current law",
        user_id="auth0|one",
        year="2026",
        geography="us",
        dataset="enhanced_cps_2024",
        number_of_provisions=3,
        api_version="1.0.0",
        added_date=1,
        updated_date=2,
        budgetary_impact=None,
        type=None,
    )


def _reform() -> LegacyPolicySnapshot:
    return LegacyPolicySnapshot(
        country_id="us",
        legacy_policy_id=2,
        api_version="1.0.0",
        policy_json={"gov.example.rate": {"2026": 0.2}},
        source_policy_hash="legacy/base64+hash=",
    )


def _saved_values() -> dict[str, object]:
    return _saved().model_dump(exclude={"legacy_user_policy_id"})


def test_success_logs_only_identifiers_outcomes_and_metric_fields() -> None:
    mirror = MagicMock()
    mirror.mirror_legacy_user_policy.return_value = LegacyUserPolicyPersistenceResult(
        association_id=ASSOCIATION_ID,
        policy_id=POLICY_ID,
        association_created=True,
        association_updated=False,
        mapping_created=True,
    )

    with patch("policyengine_api.services.user_policy_mirroring.logger") as logger:
        result = mirror_user_policy_after_commit(
            _saved(),
            _reform(),
            source_revision=3,
            changed_fields=frozenset({"reform_label"}),
            mirror_factory=lambda: mirror,
        )

    assert result.association_id == ASSOCIATION_ID
    mirror.mirror_legacy_user_policy.assert_called_once_with(
        _saved(),
        _reform(),
        source_revision=3,
        changed_fields=frozenset({"reform_label"}),
    )
    payload = logger.log_struct.call_args.args[0]
    assert payload["metric_name"] == "v1_user_policy_mirror_operations"
    assert payload["configured_write_source"] == "dual_write"
    assert payload["actual_write_sources"] == ["cloud_sql", "supabase"]
    assert payload["legacy_user_policy_id"] == 10
    assert payload["destination_association_id"] == str(ASSOCIATION_ID)
    assert payload["destination_policy_id"] == str(POLICY_ID)
    rendered = repr(payload)
    assert "gov.example.rate" not in rendered
    assert "auth0|one" not in rendered
    assert "Reform" not in rendered


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (
            OperationalError("statement secret", {}, Exception("credential")),
            "database",
        ),
        (TimeoutError("pool timeout"), "database"),
        (LegacyUserPolicyIntegrityError("mapping conflict"), "integrity"),
        (RuntimeError("caller data secret"), "unexpected"),
    ],
)
def test_failure_is_secret_safe_and_reports_only_cloud_sql_completed(
    error: Exception,
    category: str,
) -> None:
    mirror = MagicMock()
    mirror.mirror_legacy_user_policy.side_effect = error

    with (
        patch("policyengine_api.services.user_policy_mirroring.logger") as logger,
        pytest.raises(UserPolicyMirrorUnavailableError),
    ):
        mirror_user_policy_after_commit(
            _saved(),
            _reform(),
            source_revision=3,
            mirror_factory=lambda: mirror,
        )

    payload = logger.log_struct.call_args.args[0]
    assert payload["actual_write_sources"] == ["cloud_sql"]
    assert payload["failure_category"] == category
    assert payload["destination_association_id"] is None
    assert "secret" not in repr(payload)
    assert "credential" not in repr(payload)


def test_processing_marker_commit_failure_logs_error_after_supabase_commit(
    orm_session_factory,
) -> None:
    event_service = UserPolicyService(orm_session_factory)
    creation = event_service.create_or_get_user_policy(
        _saved_values(),
        record_mirror_event=True,
    )
    mirror = MagicMock()
    mirror.mirror_legacy_user_policy.return_value = LegacyUserPolicyPersistenceResult(
        association_id=ASSOCIATION_ID,
        policy_id=POLICY_ID,
        association_created=True,
        association_updated=False,
        mapping_created=True,
    )
    source_commit_error = OperationalError(
        "processed_at update secret",
        {"caller": "caller data secret"},
        Exception("database credential"),
    )

    def fail_source_commit(_session) -> None:
        raise source_commit_error

    sqlalchemy_event.listen(
        orm_session_factory.class_,
        "before_commit",
        fail_source_commit,
    )
    try:
        with (
            patch("policyengine_api.services.user_policy_mirroring.logger") as logger,
            pytest.raises(UserPolicyMirrorUnavailableError),
        ):
            mirror_pending_user_policy_events_after_commit(
                "us",
                creation.user_policy.id,
                through_revision=creation.mirror_revision,
                event_service=event_service,
                reform_snapshot_loader=lambda _country_id, _policy_id: _reform(),
                mirror_factory=lambda: mirror,
            )
    finally:
        sqlalchemy_event.remove(
            orm_session_factory.class_,
            "before_commit",
            fail_source_commit,
        )

    logger.log_struct.assert_called_once()
    payload = logger.log_struct.call_args.args[0]
    assert payload["outcome"] == "error"
    assert payload["failure_category"] == "database"
    assert payload["actual_write_sources"] == ["cloud_sql", "supabase"]
    assert payload["destination_association_id"] == str(ASSOCIATION_ID)
    assert payload["destination_policy_id"] == str(POLICY_ID)
    assert "secret" not in repr(payload)
    assert "credential" not in repr(payload)
    with orm_session_factory() as session:
        retained_event = session.scalar(select(UserPolicyMirrorEvent))
        assert retained_event.processed_at is None


def test_event_preparation_failure_logs_error_and_retains_the_event(
    orm_session_factory,
) -> None:
    event_service = UserPolicyService(orm_session_factory)
    creation = event_service.create_or_get_user_policy(
        _saved_values(),
        record_mirror_event=True,
    )
    mirror_factory = MagicMock()

    with (
        patch("policyengine_api.services.user_policy_mirroring.logger") as logger,
        pytest.raises(UserPolicyMirrorUnavailableError),
    ):
        mirror_pending_user_policy_events_after_commit(
            "us",
            creation.user_policy.id,
            through_revision=creation.mirror_revision,
            event_service=event_service,
            reform_snapshot_loader=lambda _country_id, _policy_id: None,
            mirror_factory=mirror_factory,
        )

    mirror_factory.assert_not_called()
    logger.log_struct.assert_called_once()
    payload = logger.log_struct.call_args.args[0]
    assert payload["outcome"] == "error"
    assert payload["actual_write_sources"] == ["cloud_sql"]
    assert payload["source_revision"] == creation.mirror_revision
    with orm_session_factory() as session:
        retained_event = session.scalar(select(UserPolicyMirrorEvent))
        assert retained_event.processed_at is None
