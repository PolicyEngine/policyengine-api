from __future__ import annotations

import copy
from dataclasses import dataclass
from collections.abc import Iterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data.orm import get_v1_session_factory
from policyengine_api.data.v1_models import Policy
from policyengine_api.services.v2.policies.types import LegacyPolicySnapshot
from policyengine_api.utils import hash_object


@dataclass(frozen=True)
class PolicySetResult:
    """Existing v1 return values and an optional detached mirror snapshot."""

    policy_id: int
    message: str
    is_existing_policy: bool
    snapshot: LegacyPolicySnapshot | None

    def __iter__(self) -> Iterator[int | str | bool]:
        """Preserve the established three-value internal unpacking interface."""

        yield self.policy_id
        yield self.message
        yield self.is_existing_policy


class PolicyService:
    """Policy operations with service-owned ORM transaction boundaries."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self._injected_session_factory = session_factory

    @property
    def _sessions(self) -> sessionmaker[Session]:
        return self._injected_session_factory or get_v1_session_factory()

    @staticmethod
    def _validate_policy_id(policy_id: int) -> None:
        if type(policy_id) is not int or policy_id < 0:
            raise Exception(
                f"Invalid policy ID: {policy_id}. Must be a positive integer."
            )

    def get_policy(
        self,
        country_id: str,
        policy_id: int,
    ) -> Policy | None:
        self._validate_policy_id(policy_id)
        if not country_id:
            raise ValueError("country_id cannot be empty or None")
        with self._sessions() as session:
            return self._get_policy(session, country_id, policy_id)

    @staticmethod
    def _get_policy(
        session: Session,
        country_id: str,
        policy_id: int,
    ) -> Policy | None:
        return session.scalar(
            select(Policy).where(
                Policy.country_id == country_id,
                Policy.id == policy_id,
            )
        )

    def get_policy_json(
        self,
        country_id: str,
        policy_id: int,
    ) -> Any | None:
        policy = self.get_policy(country_id, policy_id)
        return None if policy is None else policy.policy_json

    def get_policy_snapshot(
        self,
        country_id: str,
        policy_id: int,
    ) -> LegacyPolicySnapshot | None:
        """Return detached fields required to mirror one existing v1 policy."""

        policy = self.get_policy(country_id, policy_id)
        if policy is None:
            return None
        return LegacyPolicySnapshot(
            country_id=policy.country_id,
            legacy_policy_id=policy.id,
            label=policy.label,
            api_version=policy.api_version,
            policy_json=copy.deepcopy(policy.policy_json),
            source_policy_hash=policy.policy_hash,
        )

    def search_policies(
        self,
        country_id: str,
        query: str = "",
        *,
        unique_only: bool = False,
    ) -> list[Policy]:
        with self._sessions() as session:
            results = list(
                session.scalars(
                    select(Policy).where(
                        Policy.country_id == country_id,
                        Policy.label.contains(query, autoescape=True),
                    )
                )
            )
        if not unique_only:
            return results

        unique_results = []
        processed_values = set()
        for policy in results:
            identity = policy.label, policy.policy_hash
            if identity not in processed_values:
                unique_results.append(policy)
                processed_values.add(identity)
        return unique_results

    def set_policy(
        self,
        country_id: str,
        label: str | None,
        policy_json: dict,
        *,
        prepare_for_mirroring: bool = False,
    ) -> PolicySetResult:
        country_id = country_id.lower()
        if country_id not in COUNTRY_PACKAGE_VERSIONS:
            raise ValueError(f"Invalid country_id: {country_id}")

        policy_hash = hash_object(policy_json)
        with self._sessions.begin() as session:
            policy, message, is_existing_policy = self._set_policy(
                session,
                country_id,
                label,
                policy_json,
                policy_hash,
            )
            snapshot = (
                LegacyPolicySnapshot(
                    country_id=policy.country_id,
                    legacy_policy_id=policy.id,
                    label=policy.label,
                    api_version=policy.api_version,
                    policy_json=copy.deepcopy(policy.policy_json),
                    source_policy_hash=policy.policy_hash,
                )
                if prepare_for_mirroring
                else None
            )
        return PolicySetResult(
            policy_id=policy.id,
            message=message,
            is_existing_policy=is_existing_policy,
            snapshot=snapshot,
        )

    def _set_policy(
        self,
        session: Session,
        country_id: str,
        label: str | None,
        policy_json: dict,
        policy_hash: str,
    ) -> tuple[Policy, str, bool]:
        existing = self._get_unique_policy_with_label(
            session,
            country_id,
            policy_hash,
            label or None,
        )
        if existing is not None:
            return existing, "Policy already exists", True

        policy = Policy(
            country_id=country_id,
            label=label,
            policy_json=policy_json,
            policy_hash=policy_hash,
            api_version=COUNTRY_PACKAGE_VERSIONS[country_id],
        )
        session.add(policy)
        session.flush()
        return policy, "Policy created", False

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
