from __future__ import annotations

from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data.orm import get_v1_session_factory
from policyengine_api.data.v1_models import Household, Simulation
from policyengine_api.utils.population_identity import population_id_matches
from policyengine_api.utils import hash_object
from policyengine_api.spm import SPMValidationError, normalize_spm_selection


def household_storage_json(country_id: str, household_json: dict, spm=None) -> dict:
    """Keep the measurement selection in the same atomic JSON/hash as inputs."""
    if "spm" in household_json:
        raise SPMValidationError(
            "SPM_SETTINGS_INVALID", "Supply spm beside data, not inside household data."
        )
    result = deepcopy(household_json)
    selected = normalize_spm_selection(country_id, spm)
    if selected is not None:
        result["spm"] = selected
    return result


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
        *,
        for_update: bool = False,
    ) -> Household | None:
        statement = select(Household).where(
            Household.country_id == country_id,
            Household.id == household_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return session.scalar(statement)

    def create_household(
        self,
        country_id: str,
        household_json: dict,
        label: str | None,
        *,
        spm: dict | None = None,
    ) -> Household:
        household_json = household_storage_json(country_id, household_json, spm)
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
        *,
        spm: dict | None = None,
    ) -> Household:
        with self._sessions.begin() as session:
            return self._update_household(
                session,
                country_id,
                household_id,
                household_json,
                label,
                spm=spm,
            )

    @classmethod
    def _update_household(
        cls,
        session: Session,
        country_id: str,
        household_id: int,
        household_json: dict,
        label: str | None,
        *,
        spm: dict | None = None,
    ) -> Household:
        household = cls._get_household(
            session, country_id, household_id, for_update=True
        )
        if household is None:
            raise LookupError(
                f"Household #{household_id} not found for country {country_id}."
            )
        original_inputs = dict(household.household_json)
        original_inputs.pop("spm", None)
        if spm is None and household_json == original_inputs:
            # Renaming a historical household does not select a new measurement
            # or turn its saved legacy outputs into canonical results.
            household.label = label
            return household
        # Existing choices survive ordinary edits from clients which omit spm.
        selected = spm if spm is not None else household.household_json.get("spm")
        household_json = household_storage_json(country_id, household_json, selected)
        if (
            "spm" in household_json
            and household_json != household.household_json
            and session.scalar(
                select(Simulation.id)
                .where(
                    Simulation.country_id == country_id,
                    Simulation.population_type == "household",
                    population_id_matches(
                        Simulation.population_id,
                        country_id,
                        household_id,
                        "household",
                    ),
                )
                .limit(1)
            )
            is not None
        ):
            # Simulation/report identity contains this household ID. Replacing
            # the household keeps their stored outputs and receipts reproducible.
            raise SPMValidationError(
                "SPM_SETTINGS_INVALID",
                "This household is used by a simulation. Create a new household "
                "to change its inputs or SPM selection and preserve saved results.",
            )
        household.label = label
        household.household_json = household_json
        household.household_hash = hash_object(household_json)
        household.api_version = COUNTRY_PACKAGE_VERSIONS.get(country_id)
        return household
