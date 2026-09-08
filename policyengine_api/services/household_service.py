from __future__ import annotations

from collections.abc import Callable
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.exc import (
    IntegrityError,
    OperationalError,
    SQLAlchemyError,
    TimeoutError as SQLAlchemyTimeoutError,
)
from sqlalchemy.orm import Session, sessionmaker

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data.orm import get_v1_session_factory
from policyengine_api.data.v1_models import Household, HouseholdMirrorEvent
from policyengine_api.services.v2.households.transformations import (
    legacy_household_fingerprint,
)
from policyengine_api.services.v2.households.types import (
    LegacyHouseholdPersistenceResult,
    LegacyHouseholdSnapshot,
)
from policyengine_api.utils import hash_object


HOUSEHOLD_MIRROR_PAYLOAD_SCHEMA_VERSION = 1


class HouseholdMirrorEventIntegrityError(RuntimeError):
    """Raised when retained household copy input is invalid or inconsistent."""


class HouseholdPersistenceFailureCategory(StrEnum):
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    INTEGRITY = "integrity"
    DATABASE = "database"
    UNEXPECTED = "unexpected"


class HouseholdPersistenceError(RuntimeError):
    """Domain error containing only safe persistence-failure attributes."""

    def __init__(self, category: HouseholdPersistenceFailureCategory) -> None:
        super().__init__("Household persistence failed")
        self.category = HouseholdPersistenceFailureCategory(category)

    @property
    def retryable(self) -> bool:
        return self.category in {
            HouseholdPersistenceFailureCategory.TIMEOUT,
            HouseholdPersistenceFailureCategory.UNAVAILABLE,
        }

    @classmethod
    def from_exception(cls, error: Exception) -> "HouseholdPersistenceError":
        if isinstance(error, SQLAlchemyTimeoutError):
            return cls(HouseholdPersistenceFailureCategory.TIMEOUT)
        if isinstance(error, OperationalError):
            return cls(HouseholdPersistenceFailureCategory.UNAVAILABLE)
        if isinstance(error, IntegrityError):
            return cls(HouseholdPersistenceFailureCategory.INTEGRITY)
        if isinstance(error, SQLAlchemyError):
            return cls(HouseholdPersistenceFailureCategory.DATABASE)
        return cls(HouseholdPersistenceFailureCategory.UNEXPECTED)


@dataclass(frozen=True)
class PendingHouseholdMirrorEvent:
    event_id: int
    snapshot: LegacyHouseholdSnapshot
    source_fingerprint_sha256: str
    was_processed: bool


@dataclass(frozen=True)
class HouseholdCreateResult:
    household: Household
    snapshot: LegacyHouseholdSnapshot | None
    mirror_event_id: int | None


class HouseholdService:
    """Household operations with service-owned ORM transaction boundaries."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self._injected_session_factory = session_factory

    @property
    def _sessions(self) -> sessionmaker[Session]:
        return self._injected_session_factory or get_v1_session_factory()

    def get_household(
        self,
        country_id: str,
        household_id: int,
    ) -> Household | None:
        if type(household_id) is not int or household_id < 0:
            raise Exception(
                f"Invalid household ID: {household_id}. Must be a positive integer."
            )
        with self._sessions() as session:
            return self._get_household(session, country_id, household_id)

    @staticmethod
    def _get_household(
        session: Session,
        country_id: str,
        household_id: int,
    ) -> Household | None:
        return session.scalar(
            select(Household).where(
                Household.country_id == country_id,
                Household.id == household_id,
            )
        )

    def create_household(
        self,
        country_id: str,
        household_json: dict,
        label: str | None,
        *,
        record_mirror_event: bool = False,
    ) -> HouseholdCreateResult:
        try:
            with self._sessions.begin() as session:
                household = self._create_household(
                    session,
                    country_id,
                    household_json,
                    label,
                )
                snapshot = None
                event_id = None
                if record_mirror_event:
                    snapshot, event_id = self._record_mirror_event(session, household)
                result = HouseholdCreateResult(
                    household=household,
                    snapshot=snapshot,
                    mirror_event_id=event_id,
                )
        except HouseholdPersistenceError:
            raise
        except Exception as error:
            raise HouseholdPersistenceError.from_exception(error) from error
        return result

    @staticmethod
    def _snapshot(household: Household) -> LegacyHouseholdSnapshot:
        return LegacyHouseholdSnapshot(
            country_id=household.country_id,
            legacy_household_id=household.id,
            label=household.label,
            api_version=household.api_version,
            household_json=copy.deepcopy(household.household_json),
            source_household_hash=household.household_hash,
        )

    @classmethod
    def _record_mirror_event(
        cls,
        session: Session,
        household: Household,
    ) -> tuple[LegacyHouseholdSnapshot, int]:
        snapshot = cls._snapshot(household)
        event = HouseholdMirrorEvent(
            country_id=household.country_id,
            legacy_household_id=household.id,
            payload_schema_version=HOUSEHOLD_MIRROR_PAYLOAD_SCHEMA_VERSION,
            payload_json={"snapshot": snapshot.model_dump(mode="json")},
            source_fingerprint_sha256=legacy_household_fingerprint(snapshot),
        )
        session.add(event)
        session.flush()
        return snapshot, event.id

    @staticmethod
    def _decode_mirror_event(
        event: HouseholdMirrorEvent,
    ) -> PendingHouseholdMirrorEvent:
        if event.payload_schema_version != HOUSEHOLD_MIRROR_PAYLOAD_SCHEMA_VERSION:
            raise HouseholdMirrorEventIntegrityError(
                "household mirror event payload version is unsupported"
            )
        payload = event.payload_json
        if not isinstance(payload, dict) or set(payload) != {"snapshot"}:
            raise HouseholdMirrorEventIntegrityError(
                "household mirror event payload has an invalid shape"
            )
        try:
            snapshot = LegacyHouseholdSnapshot.model_validate(payload["snapshot"])
        except (TypeError, ValueError) as error:
            raise HouseholdMirrorEventIntegrityError(
                "household mirror event snapshot is invalid"
            ) from error
        if (
            snapshot.country_id != event.country_id
            or snapshot.legacy_household_id != event.legacy_household_id
        ):
            raise HouseholdMirrorEventIntegrityError(
                "household mirror event identity conflicts with its payload"
            )
        fingerprint = legacy_household_fingerprint(snapshot)
        if fingerprint != event.source_fingerprint_sha256:
            raise HouseholdMirrorEventIntegrityError(
                "household mirror event fingerprint conflicts with its payload"
            )
        return PendingHouseholdMirrorEvent(
            event_id=event.id,
            snapshot=snapshot,
            source_fingerprint_sha256=fingerprint,
            was_processed=event.processed_at is not None,
        )

    def process_mirror_event(
        self,
        country_id: str,
        legacy_household_id: int,
        *,
        processor: Callable[
            [PendingHouseholdMirrorEvent],
            LegacyHouseholdPersistenceResult,
        ],
        after_processed_commit: Callable[
            [PendingHouseholdMirrorEvent, LegacyHouseholdPersistenceResult],
            None,
        ]
        | None = None,
        require_pending: bool = False,
    ) -> LegacyHouseholdPersistenceResult:
        """Process one explicitly selected retained create event."""

        with self._sessions.begin() as session:
            event = session.scalar(
                select(HouseholdMirrorEvent)
                .where(
                    HouseholdMirrorEvent.country_id == country_id,
                    HouseholdMirrorEvent.legacy_household_id == legacy_household_id,
                )
                .with_for_update()
            )
            if event is None:
                raise HouseholdMirrorEventIntegrityError(
                    "household mirror request has no retained event"
                )
            pending = self._decode_mirror_event(event)
            if require_pending and pending.was_processed:
                raise HouseholdMirrorEventIntegrityError(
                    "household mirror event is already processed"
                )
            result = processor(pending)
            if event.processed_at is None:
                event.processed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                session.add(event)
                session.flush()
        if after_processed_commit is not None:
            after_processed_commit(pending, result)
        return result

    @staticmethod
    def _create_household(
        session: Session,
        country_id: str,
        household_json: dict,
        label: str | None,
    ) -> Household:
        household = Household(
            country_id=country_id,
            label=label,
            household_json=household_json,
            household_hash=hash_object(household_json),
            api_version=COUNTRY_PACKAGE_VERSIONS.get(country_id),
        )
        session.add(household)
        session.flush()
        return household
