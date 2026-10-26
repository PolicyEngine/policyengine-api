"""Immediate, observable mirroring of committed v1 policies into v2."""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from sqlalchemy.exc import SQLAlchemyError

from policyengine_api.data.v2.catalog.catalog_selection import (
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
)
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.gcp_logging import logger
from policyengine_api.services.v2.policies.validators import (
    LegacyPolicyMappingIntegrityError,
    LegacyPolicyTranslationError,
    PolicyCatalogValidationError,
    PolicyContentHashCollisionError,
    PolicyCreationIntegrityError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from policyengine_api.services.v2.policies.types import (
        LegacyPolicyPersistenceResult,
        LegacyPolicySnapshot,
        LegacyPolicyTranslationReason,
    )


class LegacyPolicyMirror(Protocol):
    """Supabase transaction service used after a v1 commit."""

    def mirror_legacy_policy(
        self,
        snapshot: LegacyPolicySnapshot,
    ) -> LegacyPolicyPersistenceResult:
        """Copy one committed v1 policy into v2 and map its v1 id to the result."""
        ...


class PolicyMirrorUnavailableError(RuntimeError):
    """Raised when a committed v1 policy could not be mirrored immediately."""


def _default_mirror_factory() -> LegacyPolicyMirror:
    from policyengine_api.data.v2.database import (
        get_v2_session_factory,
    )
    from policyengine_api.services.v2.policies.database_session import (
        PolicyDatabaseSession,
    )
    from policyengine_api.services.v2.policies.services import V2PolicyService

    return V2PolicyService(PolicyDatabaseSession(get_v2_session_factory()))


class PolicyCopyFailureReason(StrEnum):
    """Fixed reason codes that failed policy and saved-policy copies log.

    A translation failure logs its LegacyPolicyTranslationReason instead, such
    as ``missing_parameters``. The two sets together are every value of a copy
    record's ``failure_reason``.
    """

    CONFIGURATION = "configuration"
    CATALOG_QUERY_FAILED = "catalog_query_failed"
    CATALOG_ABSENT = "catalog_absent"
    CATALOG_VERSION_NOT_FOUND = "catalog_version_not_found"
    CATALOG_MISMATCH = "catalog_mismatch"
    MAPPING_CONFLICT = "mapping_conflict"
    CONTENT_HASH_COLLISION = "content_hash_collision"
    STORED_POLICY_INTEGRITY = "stored_policy_integrity"
    SAVED_POLICY_INTEGRITY = "saved_policy_integrity"
    MISSING_REFORM_POLICY = "missing_reform_policy"
    MISSING_MIRROR_SNAPSHOT = "missing_mirror_snapshot"
    MISSING_MIRROR_REVISION = "missing_mirror_revision"
    DATABASE_ERROR = "database_error"
    UNEXPECTED = "unexpected"


@dataclass(frozen=True)
class PolicyCopyFailure:
    """How a failed copy is logged: a broad category and a fixed reason."""

    category: str
    reason: PolicyCopyFailureReason | LegacyPolicyTranslationReason


# Checked in order, so the hash collision is matched before its integrity base
# class.
_FAILURES_BY_ERROR_TYPE: tuple[tuple[type[Exception], PolicyCopyFailure], ...] = (
    (
        V2ConfigurationError,
        PolicyCopyFailure("configuration", PolicyCopyFailureReason.CONFIGURATION),
    ),
    (
        MetadataCatalogVersionNotFoundError,
        PolicyCopyFailure(
            "catalog_or_translation",
            PolicyCopyFailureReason.CATALOG_VERSION_NOT_FOUND,
        ),
    ),
    (
        PolicyCatalogValidationError,
        PolicyCopyFailure(
            "catalog_or_translation", PolicyCopyFailureReason.CATALOG_MISMATCH
        ),
    ),
    (
        LegacyPolicyMappingIntegrityError,
        PolicyCopyFailure("integrity", PolicyCopyFailureReason.MAPPING_CONFLICT),
    ),
    (
        PolicyContentHashCollisionError,
        PolicyCopyFailure("integrity", PolicyCopyFailureReason.CONTENT_HASH_COLLISION),
    ),
    (
        PolicyCreationIntegrityError,
        PolicyCopyFailure("integrity", PolicyCopyFailureReason.STORED_POLICY_INTEGRITY),
    ),
    (
        SQLAlchemyError,
        PolicyCopyFailure("database", PolicyCopyFailureReason.DATABASE_ERROR),
    ),
)


def classify_policy_copy_failure(error: Exception) -> PolicyCopyFailure:
    """Return how a failed policy copy logs this error.

    Both fields come only from the error's type, and for a translation error
    its fixed reason, so a log record never holds policy content or error text.
    """
    if isinstance(error, LegacyPolicyTranslationError):
        return PolicyCopyFailure("catalog_or_translation", error.reason)
    if isinstance(error, MetadataCatalogUnavailableError):
        reason = (
            PolicyCopyFailureReason.CATALOG_QUERY_FAILED
            if isinstance(error.__cause__, SQLAlchemyError)
            else PolicyCopyFailureReason.CATALOG_ABSENT
        )
        return PolicyCopyFailure("catalog_or_translation", reason)
    for error_type, failure in _FAILURES_BY_ERROR_TYPE:
        if isinstance(error, error_type):
            return failure
    return PolicyCopyFailure("unexpected", PolicyCopyFailureReason.UNEXPECTED)


@dataclass(frozen=True)
class _MirrorOutcome:
    """How one immediate policy mirror ended, as its metric record reports it."""

    outcome: str
    actual_write_sources: list[str]
    destination_policy_id: object | None = None
    failure: PolicyCopyFailure | None = None
    policy_created: bool | None = None
    mapping_created: bool | None = None


def _log_mirror_event(
    *,
    snapshot: LegacyPolicySnapshot,
    started_at: float,
    mirror_outcome: _MirrorOutcome,
) -> None:
    destination_policy_id = mirror_outcome.destination_policy_id
    failure = mirror_outcome.failure
    # Metric logging must not change the mirror outcome.
    with contextlib.suppress(Exception):
        logger.log_struct(
            {
                "message": "V1 policy immediate mirror completed",
                "metric_name": "v1_policy_mirror_operations",
                "metric_value": 1,
                "configured_write_source": "dual_write",
                "attempted_write_sources": ["cloud_sql", "supabase"],
                "actual_write_sources": mirror_outcome.actual_write_sources,
                "country_id": snapshot.country_id,
                "legacy_policy_id": snapshot.legacy_policy_id,
                "destination_policy_id": (
                    str(destination_policy_id)
                    if destination_policy_id is not None
                    else None
                ),
                "outcome": mirror_outcome.outcome,
                "failure_category": failure.category if failure else None,
                "failure_reason": failure.reason.value if failure else None,
                "policy_created": mirror_outcome.policy_created,
                "mapping_created": mirror_outcome.mapping_created,
                "duration_ms": round((time.perf_counter() - started_at) * 1000, 3),
            },
            severity="INFO" if mirror_outcome.outcome == "ok" else "ERROR",
        )


def mirror_policy_after_commit(
    snapshot: LegacyPolicySnapshot,
    *,
    mirror_factory: Callable[[], LegacyPolicyMirror] | None = None,
) -> LegacyPolicyPersistenceResult:
    """Copy a committed v1 policy and its mapping into v2 in one Supabase transaction.

    Log the outcome. On failure, raise PolicyMirrorUnavailableError after
    logging it; the v1 route still returns its normal response.
    """
    started_at = time.perf_counter()
    try:
        result = (mirror_factory or _default_mirror_factory)().mirror_legacy_policy(
            snapshot
        )
    except Exception as error:
        _log_mirror_event(
            snapshot=snapshot,
            started_at=started_at,
            mirror_outcome=_MirrorOutcome(
                outcome="error",
                actual_write_sources=["cloud_sql"],
                failure=classify_policy_copy_failure(error),
            ),
        )
        msg = "The committed v1 policy could not be mirrored to v2"
        raise PolicyMirrorUnavailableError(msg) from error

    _log_mirror_event(
        snapshot=snapshot,
        started_at=started_at,
        mirror_outcome=_MirrorOutcome(
            outcome="ok",
            actual_write_sources=["cloud_sql", "supabase"],
            destination_policy_id=result.policy_id,
            policy_created=result.policy_created,
            mapping_created=result.mapping_created,
        ),
    )
    return result
