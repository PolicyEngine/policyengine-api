"""Compatibility boundaries between app-v2 labels and native v2 resources."""

from __future__ import annotations

from uuid import UUID

import pytest

from policyengine_api.data.v2.models import Policy
from policyengine_api.data.v2.policies.api_schemas import PolicyCreateRequest
from policyengine_api.data.v2.user_policies.legacy import (
    LegacyUserPolicySnapshot,
    project_legacy_user_policy,
)


POLICY_ID = UUID("00000000-0000-0000-0000-000000000010")


def test_app_v2_reform_label_maps_to_association_name_only() -> None:
    snapshot = LegacyUserPolicySnapshot(
        country_id="us",
        legacy_user_policy_id=10,
        reform_id=2,
        reform_label="User-visible app label",
        baseline_id=1,
        baseline_label="Current law",
        user_id="auth0|one",
        year="2026",
        geography="us",
        dataset=None,
        number_of_provisions=3,
        api_version="1.0.0",
        added_date=1,
        updated_date=2,
        budgetary_impact=None,
        type=None,
    )

    projection = project_legacy_user_policy(snapshot, policy_id=POLICY_ID)

    assert projection.name == "User-visible app label"
    assert projection.description is None
    assert projection.policy_id == POLICY_ID
    assert "name" not in Policy.__table__.c
    assert "description" not in Policy.__table__.c


def test_core_policy_request_rejects_association_presentation_fields() -> None:
    with pytest.raises(ValueError):
        PolicyCreateRequest.model_validate(
            {
                "country_id": "us",
                "tax_benefit_model_id": str(POLICY_ID),
                "parameter_values": [],
                "name": "User-visible app label",
            }
        )
