from __future__ import annotations

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data.orm import build_v1_session_manager
from policyengine_api.data.v1_daos import HouseholdDAO
from policyengine_api.utils import hash_object


class HouseholdService:
    def __init__(self, households: HouseholdDAO | None = None):
        self._households = households

    @property
    def households(self) -> HouseholdDAO:
        if self._households is None:
            self._households = HouseholdDAO(build_v1_session_manager())
        return self._households

    def get_household(self, country_id: str, household_id: int) -> dict | None:
        if type(household_id) is not int or household_id < 0:
            raise Exception(
                f"Invalid household ID: {household_id}. Must be a positive integer."
            )
        return self.households.get(country_id, household_id)

    def create_household(
        self,
        country_id: str,
        household_json: dict,
        label: str | None,
    ) -> int:
        return self.households.create(
            country_id,
            label,
            household_json,
            hash_object(household_json),
            COUNTRY_PACKAGE_VERSIONS.get(country_id),
        )

    def update_household(
        self,
        country_id: str,
        household_id: int,
        household_json: dict,
        label: str,
    ) -> dict:
        updated = self.households.update(
            country_id,
            household_id,
            label,
            household_json,
            hash_object(household_json),
            COUNTRY_PACKAGE_VERSIONS.get(country_id),
        )
        if not updated:
            raise LookupError(
                f"Household #{household_id} not found for country {country_id}."
            )
        return self.households.get(country_id, household_id)
