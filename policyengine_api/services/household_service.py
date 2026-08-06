from __future__ import annotations

from contextlib import contextmanager

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data.orm import build_v1_session_manager
from policyengine_api.data.v1_daos import HouseholdDAO, V1UnitOfWork
from policyengine_api.utils import hash_object


class HouseholdService:
    def __init__(
        self,
        households: HouseholdDAO | None = None,
        *,
        unit_of_work: V1UnitOfWork | None = None,
    ):
        self._households = households
        self._unit_of_work = unit_of_work

    @property
    def unit_of_work(self) -> V1UnitOfWork:
        if self._unit_of_work is None:
            self._unit_of_work = V1UnitOfWork(build_v1_session_manager())
        return self._unit_of_work

    @contextmanager
    def _repository(self, *, write: bool = False):
        if self._households is not None:
            yield self._households
            return
        boundary = self.unit_of_work.transaction if write else self.unit_of_work.read
        with boundary() as repositories:
            yield repositories.households

    def get_household(self, country_id: str, household_id: int) -> dict | None:
        if type(household_id) is not int or household_id < 0:
            raise Exception(
                f"Invalid household ID: {household_id}. Must be a positive integer."
            )
        with self._repository() as households:
            return households.get(country_id, household_id)

    def create_household(
        self,
        country_id: str,
        household_json: dict,
        label: str | None,
    ) -> int:
        with self._repository(write=True) as households:
            return households.create(
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
        with self._repository(write=True) as households:
            updated = households.update(
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
            return households.get(country_id, household_id)
