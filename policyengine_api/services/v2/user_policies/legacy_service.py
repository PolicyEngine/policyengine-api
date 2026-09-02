"""Transactional operations for mirroring v1 saved policies into v2."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlmodel import Session

from policyengine_api.data.v2.models import LegacyUserPolicyMapping
from policyengine_api.data.v2.user_policies.creates import (
    create_legacy_user_mapping,
    create_legacy_user_policy_mapping,
    create_transition_user,
    create_user_policy,
)
from policyengine_api.data.v2.user_policies.deletes import (
    delete_transition_user,
    delete_user_policy,
)
from policyengine_api.data.v2.user_policies.reads import (
    read_legacy_user_mapping,
    read_legacy_user_policy_mapping,
    read_mapped_user_policy,
    read_user,
)
from policyengine_api.data.v2.user_policies.updates import (
    update_legacy_user_policy_state,
)
from policyengine_api.services.v2.policies.legacy_service import (
    persist_legacy_policy,
)
from policyengine_api.services.v2.policies.legacy_translation import (
    LegacyPolicySnapshot,
)
from policyengine_api.services.v2.user_policies.commands import (
    UserPolicyCreateCommand,
)
from policyengine_api.services.v2.user_policies.legacy_translation import (
    USER_POLICY_FINGERPRINT_VERSION,
    LegacyUserPolicySnapshot,
    fingerprint_legacy_user_policy,
    project_legacy_user_policy,
)


class LegacyUserPolicyIntegrityError(RuntimeError):
    """Raised when source, policy, association, or mapping identity conflicts."""


@dataclass(frozen=True)
class LegacyUserPolicyPersistenceResult:
    association_id: UUID
    policy_id: UUID
    association_created: bool
    association_updated: bool
    mapping_created: bool


def resolve_legacy_user_id(
    session: Session,
    *,
    legacy_user_id: str,
    primary_country: str,
) -> UUID:
    """Return one durable v2 UUID for an exact opaque v1 user identifier."""

    existing = read_legacy_user_mapping(session, legacy_user_id, lock=True)
    if existing is not None:
        if read_user(session, existing.user_id) is None:
            raise LegacyUserPolicyIntegrityError(
                "legacy user mapping has no referenced v2 user"
            )
        return existing.user_id

    user = create_transition_user(session, primary_country=primary_country)
    created_user_id = create_legacy_user_mapping(
        session,
        legacy_user_id=legacy_user_id,
        user_id=user.id,
    )
    if created_user_id is not None:
        return created_user_id

    delete_transition_user(session, user)
    concurrent = read_legacy_user_mapping(session, legacy_user_id, lock=False)
    if concurrent is None or read_user(session, concurrent.user_id) is None:
        raise LegacyUserPolicyIntegrityError(
            "legacy user mapping conflict did not resolve to a v2 user"
        )
    return concurrent.user_id


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
    """Validate and, when newer, update one existing association mapping."""

    association = read_mapped_user_policy(session, mapping)
    if association is None:
        raise LegacyUserPolicyIntegrityError(
            "legacy user-policy mapping has no association"
        )
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
    update_legacy_user_policy_state(
        session,
        association=association,
        mapping=mapping,
        reform_label=reform_label,
        update_name=association_updated,
        fingerprint=fingerprint,
        source_revision=source_revision,
    )
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

    existing = read_legacy_user_policy_mapping(
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

    association = create_user_policy(session, projection)
    mapping_id = create_legacy_user_policy_mapping(
        session,
        country_id=country_id,
        legacy_user_policy_id=legacy_user_policy_id,
        user_policy_id=association.id,
        source_revision=source_revision,
        fingerprint_version=USER_POLICY_FINGERPRINT_VERSION,
        fingerprint=fingerprint,
    )
    if mapping_id is not None:
        return LegacyUserPolicyPersistenceResult(
            association_id=association.id,
            policy_id=projection.policy_id,
            association_created=True,
            association_updated=False,
            mapping_created=True,
        )

    delete_user_policy(session, association)
    concurrent = read_legacy_user_policy_mapping(
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


def persist_legacy_user_policy(
    session: Session,
    snapshot: LegacyUserPolicySnapshot,
    reform_snapshot: LegacyPolicySnapshot,
    *,
    source_revision: int,
    changed_fields: frozenset[str] = frozenset(),
) -> LegacyUserPolicyPersistenceResult:
    """Ensure reform, association, and identity mappings in one transaction."""

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
    projection = project_legacy_user_policy(
        snapshot,
        user_id=user_id,
        policy_id=policy_result.policy_id,
    )
    return persist_legacy_user_policy_mapping(
        session,
        country_id=snapshot.country_id,
        legacy_user_policy_id=snapshot.legacy_user_policy_id,
        reform_label=snapshot.reform_label,
        projection=projection,
        fingerprint=fingerprint_legacy_user_policy(snapshot),
        source_revision=source_revision,
        changed_fields=changed_fields,
    )
