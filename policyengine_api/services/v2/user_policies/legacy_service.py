"""Transactional operations for mirroring v1 saved policies into v2."""

from __future__ import annotations

from sqlmodel import Session

from policyengine_api.data.v2.user_policies.legacy_mappings import (
    LegacyUserPolicyIntegrityError,
    LegacyUserPolicyPersistenceResult,
    persist_legacy_user_policy_mapping,
    resolve_legacy_user_id,
)
from policyengine_api.services.v2.policies.legacy_service import (
    persist_legacy_policy,
)
from policyengine_api.services.v2.policies.legacy_translation import (
    LegacyPolicySnapshot,
)
from policyengine_api.services.v2.user_policies.legacy_translation import (
    LegacyUserPolicySnapshot,
    fingerprint_legacy_user_policy,
    project_legacy_user_policy,
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
