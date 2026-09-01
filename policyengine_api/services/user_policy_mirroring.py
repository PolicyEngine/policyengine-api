"""Immediate mirroring of committed v1 saved policies into v2 associations."""

from __future__ import annotations

from collections.abc import Callable
import time
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError

from policyengine_api.data.v2.catalog.catalog_selection import (
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
)
from policyengine_api.data.v2.policies.catalog_resolution import (
    PolicyCatalogValidationError,
)
from policyengine_api.data.v2.policies.legacy_mappings import (
    LegacyPolicyMappingIntegrityError,
)
from policyengine_api.data.v2.policies.persistence import (
    PolicyContentHashCollisionError,
    PolicyPersistenceIntegrityError,
)
from policyengine_api.data.v2.user_policies.legacy_mappings import (
    LegacyUserPolicyIntegrityError,
    LegacyUserPolicyPersistenceResult,
)
from policyengine_api.services.v2.policies.legacy_translation import (
    LegacyPolicySnapshot,
    LegacyPolicyTranslationError,
)
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.services.v2.user_policies.legacy_translation import (
    LegacyUserPolicySnapshot,
)
from policyengine_api.gcp_logging import logger
from policyengine_api.services.policy_service import PolicyService
from policyengine_api.services.user_policy_service import (
    PendingUserPolicyMirrorEvent,
    UserPolicyService,
)


class LegacyUserPolicyMirror(Protocol):
    def mirror_legacy_user_policy(
        self,
        snapshot: LegacyUserPolicySnapshot,
        reform_snapshot: LegacyPolicySnapshot,
        *,
        source_revision: int,
        changed_fields: frozenset[str],
    ) -> LegacyUserPolicyPersistenceResult: ...


class UserPolicyMirrorUnavailableError(RuntimeError):
    """Raised when a committed saved policy could not be mirrored immediately."""


def _default_mirror_factory() -> LegacyUserPolicyMirror:
    from policyengine_api.data.v2.database import get_v2_session_factory
    from policyengine_api.services.v2.user_policies.service import (
        V2UserPolicyService,
    )

    return V2UserPolicyService(get_v2_session_factory())


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
            LegacyUserPolicyIntegrityError,
            PolicyContentHashCollisionError,
            PolicyPersistenceIntegrityError,
        ),
    ):
        return "integrity"
    if isinstance(error, SQLAlchemyError):
        return "database"
    return "unexpected"


def _log_mirror_operation(
    *,
    country_id: str,
    legacy_user_policy_id: int,
    source_revision: int | None,
    requested_through_revision: int,
    started_at: float,
    outcome: str,
    actual_write_sources: list[str],
    result: LegacyUserPolicyPersistenceResult | None = None,
    failure_category: str | None = None,
) -> None:
    logger.log_struct(
        {
            "message": "V1 saved-policy immediate mirror completed",
            "metric_name": "v1_user_policy_mirror_operations",
            "metric_value": 1,
            "configured_write_source": "dual_write",
            "attempted_write_sources": ["cloud_sql", "supabase"],
            "actual_write_sources": actual_write_sources,
            "country_id": country_id,
            "legacy_user_policy_id": legacy_user_policy_id,
            "source_revision": source_revision,
            "requested_through_revision": requested_through_revision,
            "destination_association_id": (
                str(result.association_id) if result is not None else None
            ),
            "destination_policy_id": (
                str(result.policy_id) if result is not None else None
            ),
            "outcome": outcome,
            "failure_category": failure_category,
            "association_created": (
                result.association_created if result is not None else None
            ),
            "association_updated": (
                result.association_updated if result is not None else None
            ),
            "mapping_created": result.mapping_created if result is not None else None,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 3),
        },
        severity="INFO" if outcome == "ok" else "ERROR",
    )


def _run_user_policy_mirror(
    snapshot: LegacyUserPolicySnapshot,
    reform_snapshot: LegacyPolicySnapshot,
    *,
    source_revision: int,
    changed_fields: frozenset[str],
    mirror_factory: Callable[[], LegacyUserPolicyMirror] | None,
) -> LegacyUserPolicyPersistenceResult:
    return (mirror_factory or _default_mirror_factory)().mirror_legacy_user_policy(
        snapshot,
        reform_snapshot,
        source_revision=source_revision,
        changed_fields=changed_fields,
    )


def mirror_user_policy_after_commit(
    snapshot: LegacyUserPolicySnapshot,
    reform_snapshot: LegacyPolicySnapshot,
    *,
    source_revision: int,
    changed_fields: frozenset[str] = frozenset(),
    mirror_factory: Callable[[], LegacyUserPolicyMirror] | None = None,
) -> LegacyUserPolicyPersistenceResult:
    """Require one complete Supabase association transaction before v1 success."""

    started_at = time.perf_counter()
    try:
        result = _run_user_policy_mirror(
            snapshot,
            reform_snapshot,
            source_revision=source_revision,
            changed_fields=changed_fields,
            mirror_factory=mirror_factory,
        )
    except Exception as error:
        _log_mirror_operation(
            country_id=snapshot.country_id,
            legacy_user_policy_id=snapshot.legacy_user_policy_id,
            source_revision=source_revision,
            requested_through_revision=source_revision,
            started_at=started_at,
            outcome="error",
            actual_write_sources=["cloud_sql"],
            failure_category=_failure_category(error),
        )
        raise UserPolicyMirrorUnavailableError(
            "The committed v1 saved policy could not be mirrored to v2"
        ) from error

    _log_mirror_operation(
        country_id=snapshot.country_id,
        legacy_user_policy_id=snapshot.legacy_user_policy_id,
        source_revision=source_revision,
        requested_through_revision=source_revision,
        started_at=started_at,
        outcome="ok",
        actual_write_sources=["cloud_sql", "supabase"],
        result=result,
    )
    return result


def mirror_pending_user_policy_events_after_commit(
    country_id: str,
    legacy_user_policy_id: int,
    *,
    through_revision: int,
    event_service: UserPolicyService | None = None,
    reform_snapshot_loader: Callable[[str, int], LegacyPolicySnapshot | None]
    | None = None,
    mirror_factory: Callable[[], LegacyUserPolicyMirror] | None = None,
) -> LegacyUserPolicyPersistenceResult:
    """Synchronously apply retained source events through one request's revision."""

    selected_event_service = event_service or UserPolicyService()
    selected_reform_loader = (
        reform_snapshot_loader or PolicyService().get_policy_snapshot
    )
    request_started_at = time.perf_counter()
    active_event: PendingUserPolicyMirrorEvent | None = None
    event_started_at: dict[int, float] = {}
    destination_results: dict[int, LegacyUserPolicyPersistenceResult] = {}

    def process(
        event: PendingUserPolicyMirrorEvent,
    ) -> LegacyUserPolicyPersistenceResult:
        nonlocal active_event

        active_event = event
        event_started_at[event.event_id] = time.perf_counter()
        reform_snapshot = selected_reform_loader(
            event.snapshot.country_id,
            event.snapshot.reform_id,
        )
        if reform_snapshot is None:
            raise UserPolicyMirrorUnavailableError(
                "The saved policy references an unavailable reform policy"
            )
        result = _run_user_policy_mirror(
            event.snapshot,
            reform_snapshot,
            source_revision=event.source_revision,
            changed_fields=event.changed_fields,
            mirror_factory=mirror_factory,
        )
        destination_results[event.event_id] = result
        return result

    def after_processed_commit(
        event: PendingUserPolicyMirrorEvent,
        result: LegacyUserPolicyPersistenceResult,
    ) -> None:
        nonlocal active_event

        _log_mirror_operation(
            country_id=event.snapshot.country_id,
            legacy_user_policy_id=event.snapshot.legacy_user_policy_id,
            source_revision=event.source_revision,
            requested_through_revision=through_revision,
            started_at=event_started_at.pop(event.event_id),
            outcome="ok",
            actual_write_sources=["cloud_sql", "supabase"],
            result=result,
        )
        destination_results.pop(event.event_id, None)
        active_event = None

    try:
        return selected_event_service.process_pending_mirror_events(
            country_id,
            legacy_user_policy_id,
            through_revision=through_revision,
            processor=process,
            after_processed_commit=after_processed_commit,
        )
    except Exception as error:
        event = active_event
        result = destination_results.get(event.event_id) if event is not None else None
        failure = error
        if isinstance(error, UserPolicyMirrorUnavailableError) and isinstance(
            error.__cause__, Exception
        ):
            failure = error.__cause__
        _log_mirror_operation(
            country_id=(event.snapshot.country_id if event is not None else country_id),
            legacy_user_policy_id=(
                event.snapshot.legacy_user_policy_id
                if event is not None
                else legacy_user_policy_id
            ),
            source_revision=event.source_revision if event is not None else None,
            requested_through_revision=through_revision,
            started_at=(
                event_started_at.get(event.event_id, request_started_at)
                if event is not None
                else request_started_at
            ),
            outcome="error",
            actual_write_sources=(
                ["cloud_sql", "supabase"] if result is not None else ["cloud_sql"]
            ),
            result=result,
            failure_category=_failure_category(failure),
        )
        raise UserPolicyMirrorUnavailableError(
            "The committed v1 saved policy event could not be mirrored to v2"
        ) from error
