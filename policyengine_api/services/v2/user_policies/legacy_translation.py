"""Translate committed v1 saved-policy rows into v2 association commands."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Annotated
from uuid import UUID

from pydantic import Field

from policyengine_api.query_parameters import CountryId, LegacyUserId
from policyengine_api.services.v2.policies.commands import StrictPolicyCommand
from policyengine_api.services.v2.user_policies.commands import (
    UserPolicyCreateCommand,
)


USER_POLICY_FINGERPRINT_VERSION = 1


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
