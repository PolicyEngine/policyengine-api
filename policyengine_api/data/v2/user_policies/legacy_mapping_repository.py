"""Database operations for legacy users and saved-policy association mappings."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import (
    LegacyUserMapping,
    LegacyUserPolicyMapping,
    User,
    UserPolicy,
)
from policyengine_api.data.v2.models.base import utc_now
from policyengine_api.services.v2.user_policies.commands import (
    UserPolicyCreateCommand,
)

USER_POLICY_FINGERPRINT_VERSION = 1


class LegacyUserPolicyIntegrityError(RuntimeError):
    """Raised when source, policy, association, or mapping identity conflicts."""


@dataclass(frozen=True)
class LegacyUserPolicyPersistenceResult:
    association_id: UUID
    policy_id: UUID
    association_created: bool
    association_updated: bool
    mapping_created: bool


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
    inserted_user_id: UUID | None = session.execute(
        insert(LegacyUserMapping)
        .values(
            legacy_user_id=legacy_user_id,
            user_id=user.id,
        )
        .on_conflict_do_nothing(index_elements=[LegacyUserMapping.legacy_user_id])
        .returning(col(LegacyUserMapping.user_id))
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
    *,
    country_id: str,
    legacy_user_policy_id: int,
    lock: bool,
) -> LegacyUserPolicyMapping | None:
    statement = select(LegacyUserPolicyMapping).where(
        LegacyUserPolicyMapping.country_id == country_id,
        LegacyUserPolicyMapping.legacy_user_policy_id == legacy_user_policy_id,
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


def apply_existing_legacy_user_policy_mapping(
    session: Session,
    *,
    mapping: LegacyUserPolicyMapping,
    country_id: str,
    reform_label: str | None,
    fingerprint: str,
    user_id: UUID,
    policy_id: UUID,
    changed_fields: frozenset[str],
    source_revision: int,
) -> LegacyUserPolicyPersistenceResult:
    association = _mapped_association(session, mapping)
    if (
        association.policy_id != policy_id
        or association.country_id != country_id
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
        "reform_label" in changed_fields and association.name != reform_label
    )
    if association_updated:
        association.name = reform_label
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


def persist_legacy_user_policy_mapping(
    session: Session,
    *,
    country_id: str,
    legacy_user_policy_id: int,
    reform_label: str | None,
    projection: UserPolicyCreateCommand,
    fingerprint: str,
    source_revision: int,
    changed_fields: frozenset[str],
) -> LegacyUserPolicyPersistenceResult:
    """Create or advance one v1 saved-policy association mapping."""

    existing = _mapping(
        session,
        country_id=country_id,
        legacy_user_policy_id=legacy_user_policy_id,
        lock=True,
    )
    if existing is not None:
        return apply_existing_legacy_user_policy_mapping(
            session,
            mapping=existing,
            country_id=country_id,
            reform_label=reform_label,
            fingerprint=fingerprint,
            user_id=projection.user_id,
            policy_id=projection.policy_id,
            changed_fields=changed_fields,
            source_revision=source_revision,
        )

    association = UserPolicy(**projection.model_dump())
    session.add(association)
    session.flush()
    mapping_id = session.execute(
        insert(LegacyUserPolicyMapping)
        .values(
            country_id=country_id,
            legacy_user_policy_id=legacy_user_policy_id,
            user_policy_id=association.id,
            last_applied_source_revision=source_revision,
            fingerprint_version=USER_POLICY_FINGERPRINT_VERSION,
            fingerprint_sha256=fingerprint,
        )
        .on_conflict_do_nothing(
            constraint="uq_legacy_user_policy_mappings_country_legacy"
        )
        .returning(col(LegacyUserPolicyMapping.id))
    ).scalar_one_or_none()
    if mapping_id is not None:
        return LegacyUserPolicyPersistenceResult(
            association_id=association.id,
            policy_id=projection.policy_id,
            association_created=True,
            association_updated=False,
            mapping_created=True,
        )

    session.delete(association)
    session.flush()
    concurrent = _mapping(
        session,
        country_id=country_id,
        legacy_user_policy_id=legacy_user_policy_id,
        lock=False,
    )
    if concurrent is None:
        raise LegacyUserPolicyIntegrityError(
            "legacy user-policy mapping conflict did not resolve to a stored row"
        )
    return apply_existing_legacy_user_policy_mapping(
        session,
        mapping=concurrent,
        country_id=country_id,
        reform_label=reform_label,
        fingerprint=fingerprint,
        user_id=projection.user_id,
        policy_id=projection.policy_id,
        changed_fields=changed_fields,
        source_revision=source_revision,
    )
