"""Projection and durable mapping of committed v1 saved-policy rows."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Annotated
from uuid import UUID

from pydantic import Field
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, select

from policyengine_api.data.v2.models import (
    LegacyUserMapping,
    LegacyUserPolicyMapping,
    User,
    UserPolicy,
)
from policyengine_api.data.v2.models.base import utc_now
from policyengine_api.data.v2.policies.legacy import (
    LegacyPolicySnapshot,
    persist_legacy_policy,
)
from policyengine_api.data.v2.policies.schemas import StrictPolicyCommand
from policyengine_api.data.v2.user_policies.schemas import UserPolicyCreateCommand
from policyengine_api.query_parameters import CountryId, LegacyUserId


USER_POLICY_FINGERPRINT_VERSION = 1


class LegacyUserPolicyIntegrityError(RuntimeError):
    """Raised when source, policy, association, or mapping identity conflicts."""


class LegacyUserPolicySnapshot(StrictPolicyCommand):
    """Detached complete committed v1 saved-policy row."""

    country_id: CountryId
    legacy_user_policy_id: Annotated[int, Field(ge=0)]
    reform_id: Annotated[int, Field(ge=0)]
    reform_label: Annotated[str, Field(max_length=255)] | None = None
    baseline_id: Annotated[int, Field(ge=0)]
    baseline_label: Annotated[str, Field(max_length=255)] | None = None
    user_id: LegacyUserId
    year: Annotated[str, Field(max_length=32)]
    geography: Annotated[str, Field(max_length=255)]
    dataset: Annotated[str, Field(max_length=255)] | None = None
    number_of_provisions: Annotated[int, Field(ge=0)]
    api_version: Annotated[str, Field(max_length=32)]
    added_date: int
    updated_date: int
    budgetary_impact: Annotated[str, Field(max_length=255)] | None = None
    type: Annotated[str, Field(max_length=255)] | None = None


@dataclass(frozen=True)
class LegacyUserPolicyPersistenceResult:
    association_id: UUID
    policy_id: UUID
    association_created: bool
    association_updated: bool
    mapping_created: bool


def fingerprint_legacy_user_policy(snapshot: LegacyUserPolicySnapshot) -> str:
    """Hash every committed source field through deterministic JSON."""

    document = {
        "fingerprint_version": USER_POLICY_FINGERPRINT_VERSION,
        **snapshot.model_dump(mode="json"),
    }
    encoded = json.dumps(
        document,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def project_legacy_user_policy(
    snapshot: LegacyUserPolicySnapshot,
    *,
    user_id: UUID,
    policy_id: UUID,
) -> UserPolicyCreateCommand:
    """Map v1 presentation data onto an association, never core policy content."""

    return UserPolicyCreateCommand(
        country_id=snapshot.country_id,
        user_id=user_id,
        policy_id=policy_id,
        name=snapshot.reform_label,
        description=None,
    )


def _legacy_user_mapping(
    session: Session,
    legacy_user_id: str,
    *,
    lock: bool,
) -> LegacyUserMapping | None:
    statement = select(LegacyUserMapping).where(
        LegacyUserMapping.legacy_user_id == legacy_user_id
    )
    if lock:
        statement = statement.with_for_update()
    return session.exec(statement).one_or_none()


def resolve_legacy_user_id(
    session: Session,
    *,
    legacy_user_id: str,
    primary_country: str,
) -> UUID:
    """Return one durable v2 UUID for an exact opaque v1 user identifier."""

    existing = _legacy_user_mapping(session, legacy_user_id, lock=True)
    if existing is not None:
        if session.get(User, existing.user_id) is None:
            raise LegacyUserPolicyIntegrityError(
                "legacy user mapping has no referenced v2 user"
            )
        return existing.user_id

    user = User(primary_country=primary_country)
    session.add(user)
    session.flush()
    inserted_user_id = session.execute(
        insert(LegacyUserMapping)
        .values(
            legacy_user_id=legacy_user_id,
            user_id=user.id,
        )
        .on_conflict_do_nothing(index_elements=[LegacyUserMapping.legacy_user_id])
        .returning(LegacyUserMapping.user_id)
    ).scalar_one_or_none()
    if inserted_user_id is not None:
        return inserted_user_id

    session.delete(user)
    session.flush()
    concurrent = _legacy_user_mapping(session, legacy_user_id, lock=False)
    if concurrent is None or session.get(User, concurrent.user_id) is None:
        raise LegacyUserPolicyIntegrityError(
            "legacy user mapping conflict did not resolve to a v2 user"
        )
    return concurrent.user_id


def _mapping(
    session: Session,
    snapshot: LegacyUserPolicySnapshot,
    *,
    lock: bool,
) -> LegacyUserPolicyMapping | None:
    statement = select(LegacyUserPolicyMapping).where(
        LegacyUserPolicyMapping.country_id == snapshot.country_id,
        LegacyUserPolicyMapping.legacy_user_policy_id == snapshot.legacy_user_policy_id,
    )
    if lock:
        statement = statement.with_for_update()
    return session.exec(statement).one_or_none()


def _mapped_association(
    session: Session,
    mapping: LegacyUserPolicyMapping,
) -> UserPolicy:
    association = session.exec(
        select(UserPolicy).where(
            UserPolicy.id == mapping.user_policy_id,
            UserPolicy.country_id == mapping.country_id,
        )
    ).one_or_none()
    if association is None:
        raise LegacyUserPolicyIntegrityError(
            "legacy user-policy mapping has no association"
        )
    return association


def _apply_existing_mapping(
    session: Session,
    *,
    mapping: LegacyUserPolicyMapping,
    snapshot: LegacyUserPolicySnapshot,
    fingerprint: str,
    user_id: UUID,
    policy_id: UUID,
    changed_fields: frozenset[str],
    source_revision: int,
) -> LegacyUserPolicyPersistenceResult:
    association = _mapped_association(session, mapping)
    if (
        association.policy_id != policy_id
        or association.country_id != snapshot.country_id
        or association.user_id != user_id
    ):
        raise LegacyUserPolicyIntegrityError(
            "legacy user-policy mapping conflicts with immutable association fields"
        )
    if mapping.fingerprint_version != USER_POLICY_FINGERPRINT_VERSION:
        raise LegacyUserPolicyIntegrityError(
            "legacy user-policy fingerprint version is unsupported"
        )
    if source_revision < mapping.last_applied_source_revision:
        return LegacyUserPolicyPersistenceResult(
            association_id=association.id,
            policy_id=policy_id,
            association_created=False,
            association_updated=False,
            mapping_created=False,
        )
    if source_revision == mapping.last_applied_source_revision:
        if mapping.fingerprint_sha256 != fingerprint:
            raise LegacyUserPolicyIntegrityError(
                "legacy user-policy revision conflicts with its stored fingerprint"
            )
        return LegacyUserPolicyPersistenceResult(
            association_id=association.id,
            policy_id=policy_id,
            association_created=False,
            association_updated=False,
            mapping_created=False,
        )
    if source_revision != mapping.last_applied_source_revision + 1:
        raise LegacyUserPolicyIntegrityError(
            "legacy user-policy revision has an unapplied predecessor"
        )

    association_updated = (
        "reform_label" in changed_fields and association.name != snapshot.reform_label
    )
    if association_updated:
        association.name = snapshot.reform_label
        association.updated_at = utc_now()
        session.add(association)
    mapping.fingerprint_sha256 = fingerprint
    mapping.last_applied_source_revision = source_revision
    mapping.updated_at = utc_now()
    session.add(mapping)
    session.flush()
    return LegacyUserPolicyPersistenceResult(
        association_id=association.id,
        policy_id=policy_id,
        association_created=False,
        association_updated=association_updated,
        mapping_created=False,
    )


def persist_legacy_user_policy(
    session: Session,
    snapshot: LegacyUserPolicySnapshot,
    reform_snapshot: LegacyPolicySnapshot,
    *,
    source_revision: int,
    changed_fields: frozenset[str] = frozenset(),
) -> LegacyUserPolicyPersistenceResult:
    """Ensure reform, association, and both mappings in the caller transaction."""

    if source_revision <= 0:
        raise LegacyUserPolicyIntegrityError(
            "legacy user-policy source revision must be positive"
        )
    if (
        snapshot.country_id != reform_snapshot.country_id
        or snapshot.reform_id != reform_snapshot.legacy_policy_id
    ):
        raise LegacyUserPolicyIntegrityError(
            "saved policy does not reference the supplied reform snapshot"
        )
    policy_result = persist_legacy_policy(session, reform_snapshot)
    user_id = resolve_legacy_user_id(
        session,
        legacy_user_id=snapshot.user_id,
        primary_country=snapshot.country_id,
    )
    fingerprint = fingerprint_legacy_user_policy(snapshot)
    existing = _mapping(session, snapshot, lock=True)
    if existing is not None:
        return _apply_existing_mapping(
            session,
            mapping=existing,
            snapshot=snapshot,
            fingerprint=fingerprint,
            user_id=user_id,
            policy_id=policy_result.policy_id,
            changed_fields=changed_fields,
            source_revision=source_revision,
        )

    projection = project_legacy_user_policy(
        snapshot,
        user_id=user_id,
        policy_id=policy_result.policy_id,
    )
    association = UserPolicy(**projection.model_dump())
    session.add(association)
    session.flush()
    mapping_id = session.execute(
        insert(LegacyUserPolicyMapping)
        .values(
            country_id=snapshot.country_id,
            legacy_user_policy_id=snapshot.legacy_user_policy_id,
            user_policy_id=association.id,
            last_applied_source_revision=source_revision,
            fingerprint_version=USER_POLICY_FINGERPRINT_VERSION,
            fingerprint_sha256=fingerprint,
        )
        .on_conflict_do_nothing(
            constraint="uq_legacy_user_policy_mappings_country_legacy"
        )
        .returning(LegacyUserPolicyMapping.id)
    ).scalar_one_or_none()
    if mapping_id is not None:
        return LegacyUserPolicyPersistenceResult(
            association_id=association.id,
            policy_id=policy_result.policy_id,
            association_created=True,
            association_updated=False,
            mapping_created=True,
        )

    session.delete(association)
    session.flush()
    concurrent = _mapping(session, snapshot, lock=False)
    if concurrent is None:
        raise LegacyUserPolicyIntegrityError(
            "legacy user-policy mapping conflict did not resolve to a stored row"
        )
    return _apply_existing_mapping(
        session,
        mapping=concurrent,
        snapshot=snapshot,
        fingerprint=fingerprint,
        user_id=user_id,
        policy_id=policy_result.policy_id,
        changed_fields=changed_fields,
        source_revision=source_revision,
    )
