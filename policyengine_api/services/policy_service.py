from __future__ import annotations

import json

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data.orm import build_v1_session_manager
from policyengine_api.data.v1_daos import PolicyDAO
from policyengine_api.utils import hash_object


class PolicyService:
    def __init__(self, policies: PolicyDAO | None = None):
        self._policies = policies

    @property
    def policies(self) -> PolicyDAO:
        if self._policies is None:
            self._policies = PolicyDAO(build_v1_session_manager())
        return self._policies

    @staticmethod
    def _validate_policy_id(policy_id: int) -> None:
        if type(policy_id) is not int or policy_id < 0:
            raise Exception(
                f"Invalid policy ID: {policy_id}. Must be a positive integer."
            )

    def get_policy(self, country_id: str, policy_id: int) -> dict | None:
        self._validate_policy_id(policy_id)
        if not country_id:
            raise ValueError("country_id cannot be empty or None")
        return self.policies.get(country_id, policy_id)

    def get_policy_json(self, country_id: str, policy_id: int) -> str | None:
        self._validate_policy_id(policy_id)
        policy = self.policies.get(country_id, policy_id)
        if policy is None:
            return None
        value = policy["policy_json"]
        return value if isinstance(value, str) else json.dumps(value)

    def set_policy(
        self, country_id: str, label: str, policy_json: dict
    ) -> tuple[int, str, bool]:
        country_id = country_id.lower()
        if country_id not in COUNTRY_PACKAGE_VERSIONS:
            raise ValueError(f"Invalid country_id: {country_id}")

        policy_hash = hash_object(policy_json)
        existing = self.policies.find_unique(country_id, policy_hash, label or None)
        if existing:
            return existing["id"], "Policy already exists", True

        policy_id = self.policies.create(
            country_id,
            label,
            policy_json,
            policy_hash,
            COUNTRY_PACKAGE_VERSIONS[country_id],
        )
        return policy_id, "Policy created", False

    def _create_new_policy(
        self,
        country_id: str,
        policy_json: dict,
        policy_hash: str,
        label: str | None,
        api_version: str,
    ) -> None:
        self.policies.create(country_id, label, policy_json, policy_hash, api_version)

    def _get_unique_policy_with_label(
        self, country_id: str, policy_hash: str, label: str
    ) -> dict | None:
        return self.policies.find_unique(country_id, policy_hash, label or None)
