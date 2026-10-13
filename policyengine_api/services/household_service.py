"""v1 household storage and the retained events that copy new households into v2."""

from __future__ import annotations

import copy
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import (
    IntegrityError,
    OperationalError,
    SQLAlchemyError,
)
from sqlalchemy.exc import (
    TimeoutError as SQLAlchemyTimeoutError,
)

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
from policyengine_api.spm import SPMValidationError, normalize_spm_selection
from policyengine_api.utils import hash_object

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker


def household_storage_json(
    country_id: str,
    household_json: dict,
    spm: object = None,
) -> dict:
    """Keep the measurement selection in the same atomic JSON/hash as inputs.

    Only a selection the caller actually sent is stored. Certification still runs
    for every household, so an unservable bundle is rejected here too, but writing
    back the defaults it resolved would fabricate a choice nobody made: it changes
    the household hash and `GET` shape for identical inputs, and it would make the
    household's replay assert a measurement the caller never asked for.
    """
    if "spm" in household_json:
        error_code = "SPM_SETTINGS_INVALID"
        raise SPMValidationError(
            error_code, "Supply spm beside data, not inside household data."
        )
    result = deepcopy(household_json)
    selected = normalize_spm_selection(country_id, spm)
    if spm is not None and selected is not None:
        result["spm"] = selected
    return result


HOUSEHOLD_MIRROR_PAYLOAD_SCHEMA_VERSION = 1


class HouseholdMirrorEventIntegrityError(RuntimeError):
    """Raised when retained household copy input is invalid or inconsistent."""


class InvalidHouseholdIdError(Exception):
    """Raised when a household ID is not a non-negative integer."""


class HouseholdPersistenceFailureCategory(StrEnum):
    """Safe-to-report reasons a household write failed."""

    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    INTEGRITY = "integrity"
    DATABASE = "database"
    UNEXPECTED = "unexpected"


class HouseholdPersistenceError(RuntimeError):
    """Domain error containing only safe persistence-failure attributes."""

    def __init__(self, category: HouseholdPersistenceFailureCategory) -> None:
        """Record the failure category; the message never carries database details."""
        super().__init__("Household persistence failed")
        self.category = HouseholdPersistenceFailureCategory(category)

    @property
    def retryable(self) -> bool:
        """Whether a retry may succeed: true for timeouts and a database outage."""
        return self.category in {
            HouseholdPersistenceFailureCategory.TIMEOUT,
            HouseholdPersistenceFailureCategory.UNAVAILABLE,
        }

    @classmethod
    def from_exception(cls, error: Exception) -> HouseholdPersistenceError:
        """Classify a database or unexpected error as a safe persistence error."""
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
    """A validated retained household copy event, and whether it was processed."""

    event_id: int
    snapshot: LegacyHouseholdSnapshot
    source_fingerprint_sha256: str
    was_processed: bool


@dataclass(frozen=True)
class HouseholdCreateResult:
    """A newly stored v1 household, with its v2 copy snapshot and any event id."""

    household: Household
    snapshot: LegacyHouseholdSnapshot | None
    mirror_event_id: int | None


class HouseholdService:
    """Household operations with service-owned ORM transaction boundaries."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        """Use this session factory, or the application's v1 one if omitted."""
        self._injected_session_factory = session_factory

    @property
    def _sessions(self) -> sessionmaker[Session]:
        return self._injected_session_factory or get_v1_session_factory()

    def get_household(
        self,
        country_id: str,
        household_id: int,
    ) -> Household | None:
        """Return the stored household in this country, or None if there is none.

        Raise InvalidHouseholdIdError if ``household_id`` is not a non-negative int.
        """
        if type(household_id) is not int or household_id < 0:
            msg = f"Invalid household ID: {household_id}. Must be a positive integer."
            raise InvalidHouseholdIdError(msg)
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
        spm: object = None,
    ) -> HouseholdCreateResult:
        """Store a v1 household, optionally recording an event to copy it into v2.

        Raise SPMValidationError for an invalid SPM selection before writing, and
        HouseholdPersistenceError, carrying a safe category, if the write fails.
        """
        # Validate before the persistence boundary so typed input failures remain 400.
        household_json = household_storage_json(country_id, household_json, spm)
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
                    # The retained event must describe the database representation
                    # of the source row. MySQL JSON can normalize a number during
                    # insertion, making the request-side value differ from a later
                    # read of the same row.
                    session.refresh(household)
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
            msg = "household mirror event payload version is unsupported"
            raise HouseholdMirrorEventIntegrityError(msg)
        payload = event.payload_json
        if not isinstance(payload, dict) or set(payload) != {"snapshot"}:
            msg = "household mirror event payload has an invalid shape"
            raise HouseholdMirrorEventIntegrityError(msg)
        try:
            snapshot = LegacyHouseholdSnapshot.model_validate(payload["snapshot"])
        except (TypeError, ValueError) as error:
            msg = "household mirror event snapshot is invalid"
            raise HouseholdMirrorEventIntegrityError(msg) from error
        if (
            snapshot.country_id != event.country_id
            or snapshot.legacy_household_id != event.legacy_household_id
        ):
            msg = "household mirror event identity conflicts with its payload"
            raise HouseholdMirrorEventIntegrityError(msg)
        fingerprint = legacy_household_fingerprint(snapshot)
        if fingerprint != event.source_fingerprint_sha256:
            msg = "household mirror event fingerprint conflicts with its payload"
            raise HouseholdMirrorEventIntegrityError(msg)
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
                msg = "household mirror request has no retained event"
                raise HouseholdMirrorEventIntegrityError(msg)
            pending = self._decode_mirror_event(event)
            if require_pending and pending.was_processed:
                msg = "household mirror event is already processed"
                raise HouseholdMirrorEventIntegrityError(msg)
            result = processor(pending)
            if event.processed_at is None:
                event.processed_at = datetime.now(UTC).replace(tzinfo=None)
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
