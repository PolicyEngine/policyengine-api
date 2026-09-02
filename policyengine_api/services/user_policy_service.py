from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.exc import (
    IntegrityError,
    OperationalError,
    SQLAlchemyError,
    TimeoutError as SQLAlchemyTimeoutError,
)
from sqlalchemy.orm import Session, sessionmaker

from policyengine_api.data.orm import get_v1_session_factory
from policyengine_api.data.v1_models import UserPolicy, UserPolicyMirrorEvent
from policyengine_api.services.v2.user_policies.legacy_service import (
    LegacyUserPolicyPersistenceResult,
)
from policyengine_api.services.v2.user_policies.legacy_translation import (
    LegacyUserPolicySnapshot,
    fingerprint_legacy_user_policy,
)


USER_POLICY_IDENTITY_FIELDS = (
    "country_id",
    "reform_id",
    "baseline_id",
    "user_id",
    "year",
    "geography",
    "reform_label",
    "baseline_label",
    "dataset",
)
USER_POLICY_MIRROR_PAYLOAD_SCHEMA_VERSION = 1
USER_POLICY_MUTABLE_FIELDS = frozenset(
    {
        "reform_label",
        "baseline_label",
        "year",
        "geography",
        "dataset",
        "number_of_provisions",
        "api_version",
        "added_date",
        "updated_date",
        "budgetary_impact",
        "type",
    }
)


class UserPolicyMirrorEventIntegrityError(RuntimeError):
    """Raised when durable saved-policy mirror input is invalid or inconsistent."""


class UserPolicyPersistenceFailureCategory(StrEnum):
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    INTEGRITY = "integrity"
    DATABASE = "database"
    UNEXPECTED = "unexpected"


class UserPolicyPersistenceError(RuntimeError):
    """Domain error containing only safe persistence-failure attributes."""

    def __init__(self, category: UserPolicyPersistenceFailureCategory) -> None:
        super().__init__("Saved-policy persistence failed")
        self.category = UserPolicyPersistenceFailureCategory(category)

    @property
    def retryable(self) -> bool:
        return self.category in {
            UserPolicyPersistenceFailureCategory.TIMEOUT,
            UserPolicyPersistenceFailureCategory.UNAVAILABLE,
        }

    @classmethod
    def from_exception(cls, error: Exception) -> UserPolicyPersistenceError:
        if isinstance(error, SQLAlchemyTimeoutError):
            return cls(UserPolicyPersistenceFailureCategory.TIMEOUT)
        if isinstance(error, OperationalError):
            return cls(UserPolicyPersistenceFailureCategory.UNAVAILABLE)
        if isinstance(error, IntegrityError):
            return cls(UserPolicyPersistenceFailureCategory.INTEGRITY)
        if isinstance(error, SQLAlchemyError):
            return cls(UserPolicyPersistenceFailureCategory.DATABASE)
        return cls(UserPolicyPersistenceFailureCategory.UNEXPECTED)


@dataclass(frozen=True)
class PendingUserPolicyMirrorEvent:
    event_id: int
    source_revision: int
    event_type: str
    snapshot: LegacyUserPolicySnapshot
    changed_fields: frozenset[str]
    source_fingerprint_sha256: str


@dataclass(frozen=True)
class UserPolicyCreateResult:
    user_policy: UserPolicy
    created: bool
    snapshot: LegacyUserPolicySnapshot
    mirror_revision: int | None = None


@dataclass(frozen=True)
class UserPolicyUpdateResult:
    user_policy: UserPolicy
    snapshot: LegacyUserPolicySnapshot
    changed_fields: frozenset[str]
    mirror_revision: int | None = None


class UserPolicyService:
    """Saved-policy operations with service-owned ORM transactions."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self._injected_session_factory = session_factory

    @property
    def _sessions(self) -> sessionmaker[Session]:
        return self._injected_session_factory or get_v1_session_factory()

    @staticmethod
    def _snapshot(user_policy: UserPolicy) -> LegacyUserPolicySnapshot:
        return LegacyUserPolicySnapshot(
            country_id=user_policy.country_id,
            legacy_user_policy_id=user_policy.id,
            reform_id=user_policy.reform_id,
            reform_label=user_policy.reform_label,
            baseline_id=user_policy.baseline_id,
            baseline_label=user_policy.baseline_label,
            user_id=user_policy.user_id,
            year=user_policy.year,
            geography=user_policy.geography,
            dataset=user_policy.dataset,
            number_of_provisions=user_policy.number_of_provisions,
            api_version=user_policy.api_version,
            added_date=user_policy.added_date,
            updated_date=user_policy.updated_date,
            budgetary_impact=user_policy.budgetary_impact,
            type=user_policy.type,
        )

    @staticmethod
    def _find_matching_user_policy(
        session: Session,
        values: Mapping[str, Any],
        *,
        lock: bool,
    ) -> UserPolicy | None:
        statement = select(UserPolicy).where(
            *(
                getattr(UserPolicy, field) == values[field]
                for field in USER_POLICY_IDENTITY_FIELDS
            )
        )
        if lock:
            statement = statement.with_for_update()
        return session.scalar(statement)

    @classmethod
    def _record_mirror_event(
        cls,
        session: Session,
        user_policy: UserPolicy,
        *,
        event_type: str,
        changed_fields: frozenset[str],
    ) -> int:
        user_policy.mirror_revision += 1
        snapshot = cls._snapshot(user_policy)
        event = UserPolicyMirrorEvent(
            country_id=user_policy.country_id,
            legacy_user_policy_id=user_policy.id,
            source_revision=user_policy.mirror_revision,
            event_type=event_type,
            payload_schema_version=USER_POLICY_MIRROR_PAYLOAD_SCHEMA_VERSION,
            payload_json={
                "snapshot": snapshot.model_dump(mode="json"),
                "changed_fields": sorted(changed_fields),
            },
            source_fingerprint_sha256=fingerprint_legacy_user_policy(snapshot),
        )
        session.add_all((user_policy, event))
        session.flush()
        return user_policy.mirror_revision

    @staticmethod
    def _decode_mirror_event(
        event: UserPolicyMirrorEvent,
    ) -> PendingUserPolicyMirrorEvent:
        if event.payload_schema_version != USER_POLICY_MIRROR_PAYLOAD_SCHEMA_VERSION:
            raise UserPolicyMirrorEventIntegrityError(
                "saved-policy mirror event payload version is unsupported"
            )
        payload = event.payload_json
        if not isinstance(payload, dict) or set(payload) != {
            "snapshot",
            "changed_fields",
        }:
            raise UserPolicyMirrorEventIntegrityError(
                "saved-policy mirror event payload has an invalid shape"
            )
        changed_fields = payload["changed_fields"]
        if not isinstance(changed_fields, list) or not all(
            isinstance(field, str) for field in changed_fields
        ):
            raise UserPolicyMirrorEventIntegrityError(
                "saved-policy mirror event changed fields are invalid"
            )
        if (
            changed_fields != sorted(set(changed_fields))
            or not set(changed_fields) <= USER_POLICY_MUTABLE_FIELDS
        ):
            raise UserPolicyMirrorEventIntegrityError(
                "saved-policy mirror event changed fields are unsupported"
            )
        try:
            snapshot = LegacyUserPolicySnapshot.model_validate(payload["snapshot"])
        except (TypeError, ValueError) as error:
            raise UserPolicyMirrorEventIntegrityError(
                "saved-policy mirror event snapshot is invalid"
            ) from error
        if (
            snapshot.country_id != event.country_id
            or snapshot.legacy_user_policy_id != event.legacy_user_policy_id
        ):
            raise UserPolicyMirrorEventIntegrityError(
                "saved-policy mirror event source identity conflicts with its payload"
            )
        fingerprint = fingerprint_legacy_user_policy(snapshot)
        if fingerprint != event.source_fingerprint_sha256:
            raise UserPolicyMirrorEventIntegrityError(
                "saved-policy mirror event fingerprint conflicts with its payload"
            )
        if event.event_type not in {"create", "update"}:
            raise UserPolicyMirrorEventIntegrityError(
                "saved-policy mirror event type is unsupported"
            )
        if event.event_type == "create" and changed_fields:
            raise UserPolicyMirrorEventIntegrityError(
                "saved-policy create mirror event contains changed fields"
            )
        if event.event_type == "update" and not changed_fields:
            raise UserPolicyMirrorEventIntegrityError(
                "saved-policy update mirror event has no changed fields"
            )
        return PendingUserPolicyMirrorEvent(
            event_id=event.id,
            source_revision=event.source_revision,
            event_type=event.event_type,
            snapshot=snapshot,
            changed_fields=frozenset(changed_fields),
            source_fingerprint_sha256=fingerprint,
        )

    def create_or_get_user_policy(
        self,
        values: Mapping[str, Any],
        *,
        record_mirror_event: bool = False,
    ) -> UserPolicyCreateResult:
        try:
            with self._sessions.begin() as session:
                user_policy = self._find_matching_user_policy(
                    session,
                    values,
                    lock=record_mirror_event,
                )
                created = user_policy is None
                if user_policy is None:
                    user_policy = UserPolicy(**values)
                    session.add(user_policy)
                    session.flush()
                mirror_revision = None
                if record_mirror_event:
                    mirror_revision = self._record_mirror_event(
                        session,
                        user_policy,
                        event_type="create",
                        changed_fields=frozenset(),
                    )
                result = UserPolicyCreateResult(
                    user_policy=user_policy,
                    created=created,
                    snapshot=self._snapshot(user_policy),
                    mirror_revision=mirror_revision,
                )
        except UserPolicyPersistenceError:
            raise
        except Exception as error:
            raise UserPolicyPersistenceError.from_exception(error) from error
        return result

    def list_user_policies(
        self,
        country_id: str,
        user_id: str,
    ) -> list[UserPolicy]:
        with self._sessions() as session:
            return list(
                session.scalars(
                    select(UserPolicy).where(
                        UserPolicy.country_id == country_id,
                        UserPolicy.user_id == user_id,
                    )
                )
            )

    def update_user_policy(
        self,
        country_id: str,
        user_policy_id: int,
        values: Mapping[str, Any],
        *,
        record_mirror_event: bool = False,
    ) -> UserPolicyUpdateResult | None:
        try:
            with self._sessions.begin() as session:
                statement = select(UserPolicy).where(
                    UserPolicy.id == user_policy_id,
                    UserPolicy.country_id == country_id,
                )
                if record_mirror_event:
                    statement = statement.with_for_update()
                user_policy = session.scalar(statement)
                if user_policy is None:
                    return None
                for field, value in values.items():
                    setattr(user_policy, field, value)
                session.flush()
                changed_fields = frozenset(values)
                mirror_revision = None
                if record_mirror_event:
                    mirror_revision = self._record_mirror_event(
                        session,
                        user_policy,
                        event_type="update",
                        changed_fields=changed_fields,
                    )
                result = UserPolicyUpdateResult(
                    user_policy=user_policy,
                    snapshot=self._snapshot(user_policy),
                    changed_fields=changed_fields,
                    mirror_revision=mirror_revision,
                )
        except UserPolicyPersistenceError:
            raise
        except Exception as error:
            raise UserPolicyPersistenceError.from_exception(error) from error
        return result

    def process_pending_mirror_events(
        self,
        country_id: str,
        legacy_user_policy_id: int,
        *,
        through_revision: int,
        processor: Callable[
            [PendingUserPolicyMirrorEvent],
            LegacyUserPolicyPersistenceResult,
        ],
        after_processed_commit: Callable[
            [
                PendingUserPolicyMirrorEvent,
                LegacyUserPolicyPersistenceResult,
            ],
            None,
        ]
        | None = None,
    ) -> LegacyUserPolicyPersistenceResult:
        """Process retained source events in order through one request's revision."""

        latest_result: LegacyUserPolicyPersistenceResult | None = None
        while True:
            with self._sessions.begin() as session:
                event = session.scalar(
                    select(UserPolicyMirrorEvent)
                    .where(
                        UserPolicyMirrorEvent.country_id == country_id,
                        UserPolicyMirrorEvent.legacy_user_policy_id
                        == legacy_user_policy_id,
                        UserPolicyMirrorEvent.source_revision <= through_revision,
                        UserPolicyMirrorEvent.processed_at.is_(None),
                    )
                    .order_by(UserPolicyMirrorEvent.source_revision)
                    .limit(1)
                    .with_for_update()
                )
                if event is None:
                    break
                pending = self._decode_mirror_event(event)
                processed_result = processor(pending)
                event.processed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                session.add(event)
                session.flush()
            latest_result = processed_result
            if after_processed_commit is not None:
                after_processed_commit(pending, processed_result)
            if pending.source_revision == through_revision:
                break
        if latest_result is None:
            with self._sessions.begin() as session:
                event = session.scalar(
                    select(UserPolicyMirrorEvent)
                    .where(
                        UserPolicyMirrorEvent.country_id == country_id,
                        UserPolicyMirrorEvent.legacy_user_policy_id
                        == legacy_user_policy_id,
                        UserPolicyMirrorEvent.source_revision == through_revision,
                        UserPolicyMirrorEvent.processed_at.is_not(None),
                    )
                    .with_for_update()
                )
                if event is None:
                    raise UserPolicyMirrorEventIntegrityError(
                        "saved-policy mirror request has no retained event"
                    )
                pending = self._decode_mirror_event(event)
                processed_result = processor(pending)
            latest_result = processed_result
            if after_processed_commit is not None:
                after_processed_commit(pending, processed_result)
        return latest_result
