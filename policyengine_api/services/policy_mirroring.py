"""Immediate, observable mirroring of committed v1 policies into v2."""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
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
    from policyengine_api.services.v2.policies.services import (  # noqa: PLC0415  # v2 persistence loads only when a default factory runs
        V2PolicyService,
    )

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


@dataclass(frozen=True)
class _MirrorOutcome:
    """How one immediate policy mirror ended, as its metric record reports it."""

    outcome: str
    actual_write_sources: list[str]
    destination_policy_id: object | None = None
    failure_category: str | None = None
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
            mirror_outcome=_MirrorOutcome(
                outcome="error",
                actual_write_sources=["cloud_sql"],
                failure_category=_failure_category(error),
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
