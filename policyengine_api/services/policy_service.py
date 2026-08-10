from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data.orm import get_v1_session_factory
from policyengine_api.data.v1_models import Policy
from policyengine_api.utils import hash_object


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

    def set_policy(
        self,
        country_id: str,
        label: str | None,
        policy_json: dict,
    ) -> tuple[int, str, bool]:
        country_id = country_id.lower()
        if country_id not in COUNTRY_PACKAGE_VERSIONS:
            raise ValueError(f"Invalid country_id: {country_id}")

        policy_hash = hash_object(policy_json)
        with self._sessions.begin() as session:
            return self._set_policy(
                session,
                country_id,
                label,
                policy_json,
                policy_hash,
            )

    def _set_policy(
        self,
        session: Session,
        country_id: str,
        label: str | None,
        policy_json: dict,
        policy_hash: str,
    ) -> tuple[int, str, bool]:
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
