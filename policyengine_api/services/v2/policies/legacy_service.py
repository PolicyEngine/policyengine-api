"""Transactional operations for mirroring committed v1 policies into v2."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from sqlmodel import Session

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS, POLICYENGINE_VERSION
from policyengine_api.data.v2.policies.legacy_mappings import (
    LegacyPolicyMappingIntegrityError,
    find_legacy_policy_mapping,
    insert_legacy_policy_mapping,
    verify_legacy_policy_mapping,
)
from policyengine_api.data.v2.policies.persistence import (
    persist_resolved_policy,
)
from policyengine_api.services.v2.policies.legacy_translation import (
    LegacyPolicySnapshot,
    translate_legacy_policy,
)


@dataclass(frozen=True)
class LegacyPolicyPersistenceResult:
    """Destination identity and insertion outcomes for one mirror attempt."""

    policy_id: UUID
    policy_created: bool
    mapping_created: bool


def persist_legacy_policy(
    session: Session,
    snapshot: LegacyPolicySnapshot,
    *,
    running_policyengine_version: str = POLICYENGINE_VERSION,
    country_package_versions: Mapping[str, str] = COUNTRY_PACKAGE_VERSIONS,
) -> LegacyPolicyPersistenceResult:
    """Translate, deduplicate, and map one v1 policy in the caller transaction."""

    existing = find_legacy_policy_mapping(
        session,
        country_id=snapshot.country_id,
        legacy_policy_id=snapshot.legacy_policy_id,
        lock=True,
    )
    if existing is not None:
        verify_legacy_policy_mapping(
            existing,
            source_policy_hash=snapshot.source_policy_hash,
        )

    command = translate_legacy_policy(
        session,
        snapshot,
        running_policyengine_version=running_policyengine_version,
        country_package_versions=country_package_versions,
    )
    policy_result = persist_resolved_policy(session, command)
    if existing is not None:
        verify_legacy_policy_mapping(
            existing,
            source_policy_hash=snapshot.source_policy_hash,
            expected_policy_id=policy_result.policy_id,
        )
        return LegacyPolicyPersistenceResult(
            policy_id=existing.policy_id,
            policy_created=False,
            mapping_created=False,
        )

    mapping_id = insert_legacy_policy_mapping(
        session,
        country_id=snapshot.country_id,
        legacy_policy_id=snapshot.legacy_policy_id,
        source_policy_hash=snapshot.source_policy_hash,
        policy_id=policy_result.policy_id,
    )
    if mapping_id is not None:
        return LegacyPolicyPersistenceResult(
            policy_id=policy_result.policy_id,
            policy_created=policy_result.created,
            mapping_created=True,
        )

    concurrent = find_legacy_policy_mapping(
        session,
        country_id=snapshot.country_id,
        legacy_policy_id=snapshot.legacy_policy_id,
        lock=False,
    )
    if concurrent is None:
        raise LegacyPolicyMappingIntegrityError(
            "legacy policy mapping conflict did not resolve to a stored row"
        )
    verify_legacy_policy_mapping(
        concurrent,
        source_policy_hash=snapshot.source_policy_hash,
        expected_policy_id=policy_result.policy_id,
    )
    return LegacyPolicyPersistenceResult(
        policy_id=concurrent.policy_id,
        policy_created=False,
        mapping_created=False,
    )
