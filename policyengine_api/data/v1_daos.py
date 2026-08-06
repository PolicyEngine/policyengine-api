"""ORM data access objects for the existing v1 schema."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from policyengine_api.data.orm import SessionManager
from policyengine_api.data.v1_models import Household, Policy, UserProfile


def _mapping(model: Any) -> dict[str, Any]:
    return {
        column.name: getattr(model, column.name)
        for column in model.__table__.columns
    }


class PolicyDAO:
    def __init__(self, sessions: SessionManager):
        self.sessions = sessions

    def get(self, country_id: str, policy_id: int) -> dict[str, Any] | None:
        with self.sessions.session() as session:
            model = session.scalar(
                select(Policy).where(
                    Policy.country_id == country_id,
                    Policy.id == policy_id,
                )
            )
            return _mapping(model) if model else None

    def find_unique(
        self, country_id: str, policy_hash: str, label: str | None
    ) -> dict[str, Any] | None:
        with self.sessions.session() as session:
            model = session.scalar(
                select(Policy).where(
                    Policy.country_id == country_id,
                    Policy.policy_hash == policy_hash,
                    Policy.label == label,
                )
            )
            return _mapping(model) if model else None

    def create(
        self,
        country_id: str,
        label: str | None,
        policy_json: Any,
        policy_hash: str,
        api_version: str,
    ) -> int:
        def operation(session):
            next_id = (session.scalar(select(func.max(Policy.id))) or 0) + 1
            session.add(
                Policy(
                    id=next_id,
                    country_id=country_id,
                    label=label,
                    api_version=api_version,
                    policy_json=policy_json,
                    policy_hash=policy_hash,
                )
            )
            return next_id

        return self.sessions.run_in_transaction(operation)


class HouseholdDAO:
    def __init__(self, sessions: SessionManager):
        self.sessions = sessions

    def get(self, country_id: str, household_id: int) -> dict[str, Any] | None:
        with self.sessions.session() as session:
            model = session.scalar(
                select(Household).where(
                    Household.country_id == country_id,
                    Household.id == household_id,
                )
            )
            return _mapping(model) if model else None

    def create(
        self,
        country_id: str,
        label: str | None,
        household_json: Any,
        household_hash: str,
        api_version: str,
    ) -> int:
        def operation(session):
            model = Household(
                country_id=country_id,
                label=label,
                api_version=api_version,
                household_json=household_json,
                household_hash=household_hash,
            )
            session.add(model)
            session.flush()
            return model.id

        return self.sessions.run_in_transaction(operation)

    def update(
        self,
        country_id: str,
        household_id: int,
        label: str | None,
        household_json: Any,
    ) -> bool:
        def operation(session):
            model = session.scalar(
                select(Household).where(
                    Household.country_id == country_id,
                    Household.id == household_id,
                )
            )
            if model is None:
                return False
            model.label = label
            model.household_json = household_json
            return True

        return self.sessions.run_in_transaction(operation)


class UserDAO:
    def __init__(self, sessions: SessionManager):
        self.sessions = sessions

    def create_profile(
        self,
        auth0_id: str,
        username: str | None,
        primary_country: str,
        user_since: int,
    ) -> int:
        def operation(session):
            model = UserProfile(
                auth0_id=auth0_id,
                username=username,
                primary_country=primary_country,
                user_since=user_since,
            )
            session.add(model)
            session.flush()
            return model.user_id

        return self.sessions.run_in_transaction(operation)

    def get_profile(
        self,
        *,
        user_id: int | None = None,
        auth0_id: str | None = None,
    ) -> dict[str, Any] | None:
        if user_id is None and auth0_id is None:
            return None
        with self.sessions.session() as session:
            condition = (
                UserProfile.user_id == user_id
                if user_id is not None
                else UserProfile.auth0_id == auth0_id
            )
            model = session.scalar(select(UserProfile).where(condition))
            return _mapping(model) if model else None
