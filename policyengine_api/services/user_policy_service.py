from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from policyengine_api.data.orm import get_v1_session_factory
from policyengine_api.data.v1_models import UserPolicy


USER_POLICY_IDENTITY_FIELDS = (
    "country_id",
    "reform_id",
    "baseline_id",
    "user_id",
    "year",
    "geography",
    "reform_label",
    "baseline_label",
    "dataset",
)


@dataclass(frozen=True)
class UserPolicyCreateResult:
    user_policy: UserPolicy
    created: bool


class UserPolicyService:
    """Saved-policy operations with service-owned ORM transactions."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self._injected_session_factory = session_factory

    @property
    def _sessions(self) -> sessionmaker[Session]:
        return self._injected_session_factory or get_v1_session_factory()

    @staticmethod
    def _find_matching_user_policy(
        session: Session,
        values: Mapping[str, Any],
    ) -> UserPolicy | None:
        return session.scalar(
            select(UserPolicy).where(
                *(
                    getattr(UserPolicy, field) == values[field]
                    for field in USER_POLICY_IDENTITY_FIELDS
                )
            )
        )

    def create_or_get_user_policy(
        self,
        values: Mapping[str, Any],
    ) -> UserPolicyCreateResult:
        with self._sessions.begin() as session:
            user_policy = self._find_matching_user_policy(session, values)
            created = user_policy is None
            if user_policy is None:
                user_policy = UserPolicy(**values)
                session.add(user_policy)
                session.flush()
            return UserPolicyCreateResult(
                user_policy=user_policy,
                created=created,
            )

    def list_user_policies(
        self,
        country_id: str,
        user_id: str,
    ) -> list[UserPolicy]:
        with self._sessions() as session:
            return list(
                session.scalars(
                    select(UserPolicy).where(
                        UserPolicy.country_id == country_id,
                        UserPolicy.user_id == user_id,
                    )
                )
            )

    def update_user_policy(
        self,
        user_policy_id: int,
        values: Mapping[str, Any],
    ) -> UserPolicy | None:
        with self._sessions.begin() as session:
            user_policy = session.get(UserPolicy, user_policy_id)
            if user_policy is None:
                return None
            for field, value in values.items():
                setattr(user_policy, field, value)
            return user_policy
