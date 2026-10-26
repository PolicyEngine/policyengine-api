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
    LegacyPolicyTranslationReason,
    PolicyCatalogValidationError,
    PolicyContentHashCollisionError,
    PolicyCreationIntegrityError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from policyengine_api.services.v2.policies.types import (
        LegacyPolicyPersistenceResult,
        LegacyPolicySnapshot,
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


def _failure_category(error: Exception) -> str:
    if isinstance(error, V2ConfigurationError):
        return "configuration"
    if isinstance(
        error,
        (
            MetadataCatalogUnavailableError,
            MetadataCatalogVersionNotFoundError,
            PolicyCatalogValidationError,
            LegacyPolicyTranslationError,
        ),
    ):
        return "catalog_or_translation"
    if isinstance(
        error,
        (
            LegacyPolicyMappingIntegrityError,
            PolicyContentHashCollisionError,
            PolicyCreationIntegrityError,
        ),
    ):
        return "integrity"
    if isinstance(error, SQLAlchemyError):
        return "database"
    return "unexpected"


class PolicyCopyFailureReason(StrEnum):
    """Fixed reason codes a failed policy or saved-policy copy logs.

    A translation failure logs its LegacyPolicyTranslationReason value instead,
    such as ``missing_parameters``. Together the two sets are every value of a
    copy record's ``failure_reason``.
    """

    CONFIGURATION = "configuration"
    CATALOG_QUERY_FAILED = "catalog_query_failed"
    CATALOG_ABSENT = "catalog_absent"
    CATALOG_VERSION_NOT_FOUND = "catalog_version_not_found"
    CATALOG_MISMATCH = "catalog_mismatch"
    MAPPING_CONFLICT = "mapping_conflict"
    SAVED_POLICY_MAPPING_CONFLICT = "saved_policy_mapping_conflict"
    CONTENT_HASH_COLLISION = "content_hash_collision"
    STORED_POLICY_INTEGRITY = "stored_policy_integrity"
    MISSING_REFORM_POLICY = "missing_reform_policy"
    DATABASE_ERROR = "database_error"
    UNEXPECTED = "unexpected"


def policy_copy_failure_reason(error: Exception) -> str:
    """Return the fixed reason code a failed policy copy logs for this error.

    The code comes only from the error's type, and for a translation error its
    fixed reason, so a log record never holds policy content or error text.
    """
    return _failure_reason_code(error).value


# Checked in order, so the hash collision is matched before its integrity base
# class.
_FAILURE_REASONS_BY_ERROR_TYPE: tuple[
    tuple[type[Exception], PolicyCopyFailureReason], ...
] = (
    (V2ConfigurationError, PolicyCopyFailureReason.CONFIGURATION),
    (
        MetadataCatalogVersionNotFoundError,
        PolicyCopyFailureReason.CATALOG_VERSION_NOT_FOUND,
    ),
    (PolicyCatalogValidationError, PolicyCopyFailureReason.CATALOG_MISMATCH),
    (LegacyPolicyMappingIntegrityError, PolicyCopyFailureReason.MAPPING_CONFLICT),
    (PolicyContentHashCollisionError, PolicyCopyFailureReason.CONTENT_HASH_COLLISION),
    (PolicyCreationIntegrityError, PolicyCopyFailureReason.STORED_POLICY_INTEGRITY),
    (SQLAlchemyError, PolicyCopyFailureReason.DATABASE_ERROR),
)


def _failure_reason_code(
    error: Exception,
) -> PolicyCopyFailureReason | LegacyPolicyTranslationReason:
    if isinstance(error, LegacyPolicyTranslationError):
        return error.reason
    if isinstance(error, MetadataCatalogUnavailableError):
        if isinstance(error.__cause__, SQLAlchemyError):
            return PolicyCopyFailureReason.CATALOG_QUERY_FAILED
        return PolicyCopyFailureReason.CATALOG_ABSENT
    for error_type, reason in _FAILURE_REASONS_BY_ERROR_TYPE:
        if isinstance(error, error_type):
            return reason
    return PolicyCopyFailureReason.UNEXPECTED


@dataclass(frozen=True)
class _MirrorOutcome:
    """How one immediate policy mirror ended, as its metric record reports it."""

    outcome: str
    actual_write_sources: list[str]
    destination_policy_id: object | None = None
    failure_category: str | None = None
    failure_reason: str | None = None
    policy_created: bool | None = None
    mapping_created: bool | None = None


def _log_mirror_event(
    *,
    snapshot: LegacyPolicySnapshot,
    started_at: float,
    mirror_outcome: _MirrorOutcome,
) -> None:
    destination_policy_id = mirror_outcome.destination_policy_id
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
                "failure_category": mirror_outcome.failure_category,
                "failure_reason": mirror_outcome.failure_reason,
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
                failure_category=_failure_category(error),
                failure_reason=policy_copy_failure_reason(error),
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
