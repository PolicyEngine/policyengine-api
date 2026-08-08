from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data.v1_models import Policy
from policyengine_api.utils import hash_object


class PolicyService:
    """Policy operations performed through a caller-owned ORM Session."""

    @staticmethod
    def _validate_policy_id(policy_id: int) -> None:
        if type(policy_id) is not int or policy_id < 0:
            raise Exception(
                f"Invalid policy ID: {policy_id}. Must be a positive integer."
            )

    def get_policy(
        self,
        session: Session,
        country_id: str,
        policy_id: int,
    ) -> Policy | None:
        self._validate_policy_id(policy_id)
        if not country_id:
            raise ValueError("country_id cannot be empty or None")
        return session.scalar(
            select(Policy).where(
                Policy.country_id == country_id,
                Policy.id == policy_id,
            )
        )

    def get_policy_json(
        self,
        session: Session,
        country_id: str,
        policy_id: int,
    ) -> Any | None:
        policy = self.get_policy(session, country_id, policy_id)
        return None if policy is None else policy.policy_json

    def set_policy(
        self,
        session: Session,
        country_id: str,
        label: str | None,
        policy_json: dict,
    ) -> tuple[int, str, bool]:
        country_id = country_id.lower()
        if country_id not in COUNTRY_PACKAGE_VERSIONS:
            raise ValueError(f"Invalid country_id: {country_id}")

        policy_hash = hash_object(policy_json)
        existing = self._get_unique_policy_with_label(
            session,
            country_id,
            policy_hash,
            label or None,
        )
        if existing is not None:
            return existing.id, "Policy already exists", True

        policy = Policy(
            country_id=country_id,
            label=label,
            policy_json=policy_json,
            policy_hash=policy_hash,
            api_version=COUNTRY_PACKAGE_VERSIONS[country_id],
        )
        session.add(policy)
        session.flush()
        return policy.id, "Policy created", False

    def _create_new_policy(
        self,
        session: Session,
        country_id: str,
        policy_json: dict,
        policy_hash: str,
        label: str | None,
        api_version: str,
    ) -> Policy:
        policy = Policy(
            country_id=country_id,
            label=label,
            policy_json=policy_json,
            policy_hash=policy_hash,
            api_version=api_version,
        )
        session.add(policy)
        session.flush()
        return policy

    def _get_unique_policy_with_label(
        self,
        session: Session,
        country_id: str,
        policy_hash: str,
        label: str | None,
    ) -> Policy | None:
        return session.scalar(
            select(Policy).where(
                Policy.country_id == country_id,
                Policy.policy_hash == policy_hash,
                Policy.label == label,
            )
        )
