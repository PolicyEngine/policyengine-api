"""Immediate, observable mirroring of committed v1 policies into v2."""

from __future__ import annotations

from collections.abc import Callable
import time
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError

from policyengine_api.data.v2.catalog.catalog_selection import (
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
)
from policyengine_api.services.v2.policies.catalog_validation import (
    PolicyCatalogValidationError,
)
from policyengine_api.services.v2.policies.creation import (
    PolicyContentHashCollisionError,
    PolicyCreationIntegrityError,
)
from policyengine_api.services.v2.policies.legacy_service import (
    LegacyPolicyMappingIntegrityError,
)
from policyengine_api.services.v2.policies.legacy_service import (
    LegacyPolicyPersistenceResult,
)
from policyengine_api.services.v2.policies.legacy_translation import (
    LegacyPolicySnapshot,
    LegacyPolicyTranslationError,
)
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.gcp_logging import logger


class LegacyPolicyMirror(Protocol):
    """Supabase transaction service used after a v1 commit."""

    def mirror_legacy_policy(
        self,
        snapshot: LegacyPolicySnapshot,
    ) -> LegacyPolicyPersistenceResult: ...


class PolicyMirrorUnavailableError(RuntimeError):
    """Raised when a committed v1 policy could not be mirrored immediately."""


def _default_mirror_factory() -> LegacyPolicyMirror:
    from policyengine_api.data.v2.database import get_v2_session_factory
    from policyengine_api.services.v2.policies.service import V2PolicyService

    return V2PolicyService(get_v2_session_factory())


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


def _log_mirror_event(
    *,
    snapshot: LegacyPolicySnapshot,
    started_at: float,
    outcome: str,
    actual_write_sources: list[str],
    destination_policy_id: object | None = None,
    failure_category: str | None = None,
    policy_created: bool | None = None,
    mapping_created: bool | None = None,
) -> None:
    logger.log_struct(
        {
            "message": "V1 policy immediate mirror completed",
            "metric_name": "v1_policy_mirror_operations",
            "metric_value": 1,
            "configured_write_source": "dual_write",
            "attempted_write_sources": ["cloud_sql", "supabase"],
            "actual_write_sources": actual_write_sources,
            "country_id": snapshot.country_id,
            "legacy_policy_id": snapshot.legacy_policy_id,
            "destination_policy_id": (
                str(destination_policy_id)
                if destination_policy_id is not None
                else None
            ),
            "outcome": outcome,
            "failure_category": failure_category,
            "policy_created": policy_created,
            "mapping_created": mapping_created,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 3),
        },
        severity="INFO" if outcome == "ok" else "ERROR",
    )


def mirror_policy_after_commit(
    snapshot: LegacyPolicySnapshot,
    *,
    mirror_factory: Callable[[], LegacyPolicyMirror] | None = None,
) -> LegacyPolicyPersistenceResult:
    """Require the Supabase policy and mapping transaction before v1 success."""

    started_at = time.perf_counter()
    try:
        result = (mirror_factory or _default_mirror_factory)().mirror_legacy_policy(
            snapshot
        )
    except Exception as error:
        _log_mirror_event(
            snapshot=snapshot,
            started_at=started_at,
            outcome="error",
            actual_write_sources=["cloud_sql"],
            failure_category=_failure_category(error),
        )
        raise PolicyMirrorUnavailableError(
            "The committed v1 policy could not be mirrored to v2"
        ) from error

    _log_mirror_event(
        snapshot=snapshot,
        started_at=started_at,
        outcome="ok",
        actual_write_sources=["cloud_sql", "supabase"],
        destination_policy_id=result.policy_id,
        policy_created=result.policy_created,
        mapping_created=result.mapping_created,
    )
    return result
