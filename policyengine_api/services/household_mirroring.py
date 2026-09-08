"""Immediate copying of one retained v1 household create event into v2."""

from __future__ import annotations

from collections.abc import Callable
import time
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError

from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.gcp_logging import logger
from policyengine_api.services.household_service import (
    HouseholdMirrorEventIntegrityError,
    HouseholdService,
    PendingHouseholdMirrorEvent,
)
from policyengine_api.services.v2.households.types import (
    LegacyHouseholdPersistenceResult,
    LegacyHouseholdSnapshot,
)
from policyengine_api.services.v2.households.validators import (
    HouseholdContentHashCollisionError,
    HouseholdCreationIntegrityError,
    LegacyHouseholdMappingIntegrityError,
    LegacyHouseholdTranslationError,
)


class LegacyHouseholdMirror(Protocol):
    """Supabase transaction service used after a v1 commit."""

    def mirror_legacy_household(
        self,
        snapshot: LegacyHouseholdSnapshot,
    ) -> LegacyHouseholdPersistenceResult: ...


class HouseholdMirrorUnavailableError(RuntimeError):
    """Raised when one committed v1 household event was not copied completely."""


def _default_mirror_factory() -> LegacyHouseholdMirror:
    from policyengine_api.data.v2.database import get_v2_session_factory
    from policyengine_api.services.v2.households.database_session import (
        HouseholdDatabaseSession,
    )
    from policyengine_api.services.v2.households.services import V2HouseholdService

    return V2HouseholdService(HouseholdDatabaseSession(get_v2_session_factory()))


def _failure_category(error: Exception) -> str:
    if isinstance(error, V2ConfigurationError):
        return "configuration"
    if isinstance(error, LegacyHouseholdTranslationError):
        return "translation"
    if isinstance(
        error,
        (
            HouseholdMirrorEventIntegrityError,
            LegacyHouseholdMappingIntegrityError,
            HouseholdContentHashCollisionError,
            HouseholdCreationIntegrityError,
        ),
    ):
        return "integrity"
    if isinstance(error, SQLAlchemyError):
        return "database"
    return "unexpected"


def _log_copy_operation(
    *,
    country_id: str,
    legacy_household_id: int,
    started_at: float,
    outcome: str,
    actual_write_sources: list[str],
    pending_event: bool,
    result: LegacyHouseholdPersistenceResult | None = None,
    failure_category: str | None = None,
) -> None:
    logger.log_struct(
        {
            "message": "V1 household immediate copy completed",
            "metric_name": "v1_household_mirror_operations",
            "metric_value": 1,
            "configured_write_source": "dual_write",
            "attempted_write_sources": ["cloud_sql", "supabase"],
            "actual_write_sources": actual_write_sources,
            "country_id": country_id,
            "legacy_household_id": legacy_household_id,
            "destination_household_id": (
                str(result.household_id) if result is not None else None
            ),
            "outcome": outcome,
            "failure_category": failure_category,
            "household_created": (
                result.household_created if result is not None else None
            ),
            "mapping_created": result.mapping_created if result is not None else None,
            "pending_event": pending_event,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 3),
        },
        severity="INFO" if outcome == "ok" else "ERROR",
    )


def process_household_event_after_commit(
    country_id: str,
    legacy_household_id: int,
    *,
    event_service: HouseholdService | None = None,
    mirror_factory: Callable[[], LegacyHouseholdMirror] | None = None,
    require_pending: bool = False,
) -> LegacyHouseholdPersistenceResult:
    """Copy one exact retained create event and then record its completion."""

    selected_event_service = event_service or HouseholdService()
    started_at = time.perf_counter()
    destination_result: LegacyHouseholdPersistenceResult | None = None

    def process(
        event: PendingHouseholdMirrorEvent,
    ) -> LegacyHouseholdPersistenceResult:
        nonlocal destination_result
        destination_result = (
            mirror_factory or _default_mirror_factory
        )().mirror_legacy_household(event.snapshot)
        return destination_result

    def after_processed_commit(
        event: PendingHouseholdMirrorEvent,
        result: LegacyHouseholdPersistenceResult,
    ) -> None:
        _log_copy_operation(
            country_id=event.snapshot.country_id,
            legacy_household_id=event.snapshot.legacy_household_id,
            started_at=started_at,
            outcome="ok",
            actual_write_sources=["cloud_sql", "supabase"],
            pending_event=False,
            result=result,
        )

    try:
        return selected_event_service.process_mirror_event(
            country_id,
            legacy_household_id,
            processor=process,
            after_processed_commit=after_processed_commit,
            require_pending=require_pending,
        )
    except Exception as error:
        _log_copy_operation(
            country_id=country_id,
            legacy_household_id=legacy_household_id,
            started_at=started_at,
            outcome="error",
            actual_write_sources=(
                ["cloud_sql", "supabase"]
                if destination_result is not None
                else ["cloud_sql"]
            ),
            pending_event=True,
            result=destination_result,
            failure_category=_failure_category(error),
        )
        raise HouseholdMirrorUnavailableError(
            "The committed v1 household event could not be copied to v2"
        ) from error
