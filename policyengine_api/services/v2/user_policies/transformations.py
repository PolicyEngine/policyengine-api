"""Pure representation transformations for v2 user-policy operations."""

from __future__ import annotations

from hashlib import sha256
import json
from uuid import UUID

from policyengine_api.data.v2.models import UserPolicy
from policyengine_api.services.v2.user_policies.types import (
    LegacyUserPolicySnapshot,
    UserPolicyCreationInput,
    UserPolicyPage,
    UserPolicyRead,
)


USER_POLICY_FINGERPRINT_VERSION = 1


def user_policy_read(association: UserPolicy) -> UserPolicyRead:
    return UserPolicyRead(
        id=association.id,
        country_id=association.country_id,
        user_id=association.user_id,
        policy_id=association.policy_id,
        name=association.name,
        description=association.description,
        created_at=association.created_at,
        updated_at=association.updated_at,
    )


def user_policy_page(
    rows: list[UserPolicy], *, offset: int, limit: int
) -> UserPolicyPage:
    return UserPolicyPage(
        items=tuple(user_policy_read(row) for row in rows[:limit]),
        offset=offset,
        limit=limit,
        has_more=len(rows) > limit,
    )


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
) -> UserPolicyCreationInput:
    """Map v1 presentation data onto an association, never core policy content."""

    return UserPolicyCreationInput(
        country_id=snapshot.country_id,
        user_id=user_id,
        policy_id=policy_id,
        name=snapshot.reform_label,
        description=None,
    )


def legacy_name_requires_update(
    association: UserPolicy,
    *,
    reform_label: str | None,
    changed_fields: frozenset[str],
) -> bool:
    return "reform_label" in changed_fields and association.name != reform_label
