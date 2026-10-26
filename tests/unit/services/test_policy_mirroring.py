"""Immediate v1 policy mirror orchestration and observability tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from policyengine_api.data.v2.catalog.catalog_selection import (
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
)
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.services.policy_mirroring import (
    PolicyCopyFailureCategory,
    PolicyCopyFailureReason,
    PolicyMirrorUnavailableError,
    classify_policy_copy_failure,
    mirror_policy_after_commit,
)
from policyengine_api.services.v2.policies.types import (
    LegacyPolicyPersistenceResult,
    LegacyPolicySnapshot,
    LegacyPolicyTranslationReason,
)
from policyengine_api.services.v2.policies.validators import (
    LegacyPolicyMappingIntegrityError,
    LegacyPolicyTranslationError,
    PolicyCatalogValidationError,
    PolicyContentHashCollisionError,
    PolicyCreationIntegrityError,
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
        "failure_reason": None,
        "policy_created": True,
        "mapping_created": True,
    }
    rendered = repr(payload)
    assert "gov.example.rate" not in rendered
    assert "legacy/base64" not in rendered


def test_logging_failure_does_not_change_successful_mirror_result() -> None:
    mirror = MagicMock()
    mirror.mirror_legacy_policy.return_value = LegacyPolicyPersistenceResult(
        policy_id=POLICY_ID,
        policy_created=True,
        mapping_created=True,
    )

    with patch(
        "policyengine_api.services.policy_mirroring.logger.log_struct",
        side_effect=RuntimeError("logging unavailable"),
    ):
        result = mirror_policy_after_commit(
            _snapshot(),
            mirror_factory=lambda: mirror,
        )

    assert result.policy_id == POLICY_ID


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (
            OperationalError("statement secret", {}, Exception("credential")),
            "database",
        ),
        (PoolTimeoutError("pool timeout"), "database"),
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


def _catalog_query_failure() -> MetadataCatalogUnavailableError:
    error = MetadataCatalogUnavailableError("the v2 metadata catalog cannot be queried")
    error.__cause__ = OperationalError("select secret", {}, Exception("credential"))
    return error


def _translation_failure(
    reason: LegacyPolicyTranslationReason,
) -> LegacyPolicyTranslationError:
    return LegacyPolicyTranslationError("gov.private.secret", reason=reason)


@pytest.mark.parametrize(
    ("error", "category", "reason"),
    [
        pytest.param(
            V2ConfigurationError("secret url"),
            "configuration",
            "configuration",
            id="configuration",
        ),
        pytest.param(
            _catalog_query_failure(),
            "catalog_or_translation",
            "catalog_query_failed",
            id="catalog-query-failed",
        ),
        pytest.param(
            MetadataCatalogUnavailableError("catalog absent secret"),
            "catalog_or_translation",
            "catalog_absent",
            id="catalog-absent",
        ),
        pytest.param(
            MetadataCatalogVersionNotFoundError("secret"),
            "catalog_or_translation",
            "catalog_version_not_found",
            id="catalog-version-not-found",
        ),
        pytest.param(
            PolicyCatalogValidationError("secret"),
            "catalog_or_translation",
            "catalog_mismatch",
            id="catalog-mismatch",
        ),
        *(
            pytest.param(
                _translation_failure(reason),
                "catalog_or_translation",
                reason.value,
                id=reason.value,
            )
            for reason in LegacyPolicyTranslationReason
        ),
        pytest.param(
            LegacyPolicyMappingIntegrityError("secret"),
            "integrity",
            "mapping_conflict",
            id="mapping-conflict",
        ),
        pytest.param(
            PolicyContentHashCollisionError("secret"),
            "integrity",
            "content_hash_collision",
            id="content-hash-collision",
        ),
        pytest.param(
            PolicyCreationIntegrityError("secret"),
            "integrity",
            "stored_policy_integrity",
            id="stored-policy-integrity",
        ),
        pytest.param(
            PoolTimeoutError("pool timeout secret"),
            "database",
            "database_error",
            id="database",
        ),
        pytest.param(
            RuntimeError("policy content secret"),
            "unexpected",
            "unexpected",
            id="unexpected",
        ),
    ],
)
def test_each_failed_copy_logs_a_fixed_reason_with_its_category(
    error: Exception,
    category: str,
    reason: str,
) -> None:
    mirror = MagicMock()
    mirror.mirror_legacy_policy.side_effect = error

    with (
        patch("policyengine_api.services.policy_mirroring.logger") as logger,
        pytest.raises(PolicyMirrorUnavailableError),
    ):
        mirror_policy_after_commit(_snapshot(), mirror_factory=lambda: mirror)

    payload = logger.log_struct.call_args.args[0]
    assert (payload["failure_category"], payload["failure_reason"]) == (
        category,
        reason,
    )
    assert type(payload["failure_reason"]) is str
    assert "secret" not in repr(payload)
    assert "credential" not in repr(payload)


@pytest.mark.parametrize(
    "error",
    [
        V2ConfigurationError("secret url"),
        MetadataCatalogUnavailableError("catalog absent"),
        _translation_failure(LegacyPolicyTranslationReason.MISSING_PARAMETERS),
        LegacyPolicyMappingIntegrityError("secret"),
        PoolTimeoutError("pool timeout"),
        RuntimeError("policy content secret"),
    ],
)
def test_failure_category_and_reason_come_from_fixed_sets(error: Exception) -> None:
    failure = classify_policy_copy_failure(error)

    assert isinstance(failure.category, PolicyCopyFailureCategory)
    assert isinstance(
        failure.reason, (PolicyCopyFailureReason, LegacyPolicyTranslationReason)
    )
