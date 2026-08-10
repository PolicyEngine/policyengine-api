from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data.orm import get_v1_session_factory
from policyengine_api.data.v1_models import Household
from policyengine_api.utils import hash_object


class HouseholdService:
    """Household operations with service-owned ORM transaction boundaries."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self._injected_session_factory = session_factory

    @property
    def _sessions(self) -> sessionmaker[Session]:
        return self._injected_session_factory or get_v1_session_factory()

    def get_household(
        self,
        country_id: str,
        household_id: int,
    ) -> Household | None:
        if type(household_id) is not int or household_id < 0:
            raise Exception(
                f"Invalid household ID: {household_id}. Must be a positive integer."
            )
        with self._sessions() as session:
            return self._get_household(session, country_id, household_id)

    @staticmethod
    def _get_household(
        session: Session,
        country_id: str,
        household_id: int,
    ) -> Household | None:
        return session.scalar(
            select(Household).where(
                Household.country_id == country_id,
                Household.id == household_id,
            )
        )

    def create_household(
        self,
        country_id: str,
        household_json: dict,
        label: str | None,
    ) -> Household:
        with self._sessions.begin() as session:
            return self._create_household(
                session,
                country_id,
                household_json,
                label,
            )

    @staticmethod
    def _create_household(
        session: Session,
        country_id: str,
        household_json: dict,
        label: str | None,
    ) -> Household:
        household = Household(
            country_id=country_id,
            label=label,
            household_json=household_json,
            household_hash=hash_object(household_json),
            api_version=COUNTRY_PACKAGE_VERSIONS.get(country_id),
        )
        session.add(household)
        session.flush()
        return household

    def update_household(
        self,
        country_id: str,
        household_id: int,
        household_json: dict,
        label: str | None,
    ) -> Household:
        with self._sessions.begin() as session:
            return self._update_household(
                session,
                country_id,
                household_id,
                household_json,
                label,
            )

    @classmethod
    def _update_household(
        cls,
        session: Session,
        country_id: str,
        household_id: int,
        household_json: dict,
        label: str | None,
    ) -> Household:
        household = cls._get_household(session, country_id, household_id)
        if household is None:
            raise LookupError(
                f"Household #{household_id} not found for country {country_id}."
            )
        household.label = label
        household.household_json = household_json
        household.household_hash = hash_object(household_json)
        household.api_version = COUNTRY_PACKAGE_VERSIONS.get(country_id)
        return household
