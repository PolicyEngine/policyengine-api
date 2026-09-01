"""Immediate v1 policy mirror orchestration and observability tests."""

from __future__ import annotations

from uuid import UUID
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError, TimeoutError

from policyengine_api.data.v2.policies.legacy import (
    LegacyPolicyMappingIntegrityError,
    LegacyPolicyPersistenceResult,
    LegacyPolicySnapshot,
)
from policyengine_api.services.policy_mirroring import (
    PolicyMirrorUnavailableError,
    mirror_policy_after_commit,
)


POLICY_ID = UUID("00000000-0000-0000-0000-000000000010")


def _snapshot() -> LegacyPolicySnapshot:
    return LegacyPolicySnapshot(
        country_id="us",
        legacy_policy_id=42,
        label="Legacy label",
        api_version="1.0.0",
        policy_json={"gov.example.rate": {"2026": 0.2}},
        source_policy_hash="legacy/base64+hash=",
    )


def test_success_returns_destination_and_logs_metric_without_policy_content() -> None:
    mirror = MagicMock()
    mirror.mirror_legacy_policy.return_value = LegacyPolicyPersistenceResult(
        policy_id=POLICY_ID,
        policy_created=True,
        mapping_created=True,
    )

    with patch("policyengine_api.services.policy_mirroring.logger") as logger:
        result = mirror_policy_after_commit(
            _snapshot(),
            mirror_factory=lambda: mirror,
        )

    assert result.policy_id == POLICY_ID
    payload = logger.log_struct.call_args.args[0]
    assert payload == {
        **payload,
        "metric_name": "v1_policy_mirror_operations",
        "metric_value": 1,
        "configured_write_source": "dual_write",
        "attempted_write_sources": ["cloud_sql", "supabase"],
        "actual_write_sources": ["cloud_sql", "supabase"],
        "country_id": "us",
        "legacy_policy_id": 42,
        "destination_policy_id": str(POLICY_ID),
        "outcome": "ok",
        "failure_category": None,
        "policy_created": True,
        "mapping_created": True,
    }
    rendered = repr(payload)
    assert "gov.example.rate" not in rendered
    assert "legacy/base64" not in rendered


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (
            OperationalError("statement secret", {}, Exception("credential")),
            "database",
        ),
        (TimeoutError("pool timeout"), "database"),
        (LegacyPolicyMappingIntegrityError("changed source hash"), "integrity"),
        (RuntimeError("policy content secret"), "unexpected"),
    ],
)
def test_failure_is_secret_safe_and_records_cloud_sql_as_only_completed_write(
    error: Exception,
    category: str,
) -> None:
    mirror = MagicMock()
    mirror.mirror_legacy_policy.side_effect = error

    with (
        patch("policyengine_api.services.policy_mirroring.logger") as logger,
        pytest.raises(PolicyMirrorUnavailableError, match="could not be mirrored"),
    ):
        mirror_policy_after_commit(_snapshot(), mirror_factory=lambda: mirror)

    payload = logger.log_struct.call_args.args[0]
    assert payload["outcome"] == "error"
    assert payload["failure_category"] == category
    assert payload["actual_write_sources"] == ["cloud_sql"]
    assert payload["destination_policy_id"] is None
    assert "secret" not in repr(payload)
    assert "credential" not in repr(payload)
