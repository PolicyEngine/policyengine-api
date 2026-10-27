"""Calculate stored households through the simulation service, and read them.

Submitting a calculation checks the country's ``countries`` row allows
household calculations (a household-only country does), reads the stored
household and policy through the same services as ``/v2/households`` and
``/v2/policies`` (so a household or policy of another country, or none, is
not found), selects the country's running catalog version, and sends the
simulation service everything it needs: it cannot read these tables. The
simulation service records every calculation, so one not saved to an
account is still stored, as a simulation run with no report.

Reading a calculation asks the simulation service for it as it stands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from policyengine_api.services.v2.household_calculations.transformations import (
    household_situation,
    policy_parameters,
    saved_spm_choice,
)
from policyengine_api.services.v2.household_calculations.types import (
    HouseholdCalculationRead,
)
from policyengine_api.services.v2.household_calculations.validators import (
    HouseholdCalculationNotFoundError,
    calculation_year,
    require_household_country,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from policyengine_api.services.v2.household_calculations.types import (
        CatalogSource,
        CountrySource,
        HouseholdCalculationInput,
        HouseholdSource,
        PolicySource,
        SimulationHouseholdCalculations,
    )


class V2HouseholdCalculationService:
    """Submit household calculations to the simulation service and read them."""

    def __init__(
        self,
        *,
        countries: CountrySource,
        households: HouseholdSource,
        policies: PolicySource,
        catalog_reader_factory: Callable[[], CatalogSource],
        simulation: SimulationHouseholdCalculations,
    ) -> None:
        """Read through these services for one request.

        ``catalog_reader_factory`` opens a catalog reader, with its own
        database session, only once a submission needs the catalog version.
        """
        self._countries = countries
        self._households = households
        self._policies = policies
        self._catalog_reader_factory = catalog_reader_factory
        self._simulation = simulation

    def submit_calculation(
        self, calculation: HouseholdCalculationInput
    ) -> HouseholdCalculationRead:
        """Send the calculation to the simulation service and return it.

        Raise HouseholdCalculationCountryError, HouseholdNotFoundError,
        PolicyNotFoundError or HouseholdCalculationYearError before anything
        is sent, and the simulation errors when the service cannot calculate.
        """
        country_id = calculation.country_id
        require_household_country(self._countries.list_countries(), country_id)
        household = self._households.get_household(
            country_id=country_id, household_id=calculation.household_id
        )
        parameters: dict[str, dict[str, Any]] = {}
        if calculation.policy_id is not None:
            parameters = policy_parameters(
                self._policies.get_policy(
                    country_id=country_id, policy_id=calculation.policy_id
                )
            )
        year = calculation_year(household.default_year)
        catalog_reader = self._catalog_reader_factory()
        try:
            catalog = catalog_reader.get_model_by_country(country_id)
        finally:
            catalog_reader.close()
        submission: dict[str, Any] = {
            "country": country_id,
            "catalog_version_id": str(catalog.model_version.id),
            "policyengine_version": catalog.policyengine_version,
            "year": year,
            "household_id": str(household.id),
            "household": household_situation(country_id, household.household_data),
            "policy": {
                "policy_id": (
                    None
                    if calculation.policy_id is None
                    else str(calculation.policy_id)
                ),
                "parameters": parameters,
            },
            "options": {
                "axes": (
                    None
                    if calculation.axes is None
                    else [
                        [
                            axis.model_dump(mode="json", exclude_unset=True)
                            for axis in group
                        ]
                        for group in calculation.axes
                    ]
                ),
                "add_missing_variables": calculation.add_missing_variables,
            },
            # A calculation is reused for 28 days after it succeeded; callers
            # without an account must not start new Modal calls at will.
            "force": False,
            "trigger": "initial",
        }
        spm = saved_spm_choice(household.household_data)
        if spm is not None:
            submission["spm"] = spm
        return HouseholdCalculationRead.from_simulation(
            self._simulation.submit(submission)
        )

    def get_calculation(self, calculation_id: UUID) -> HouseholdCalculationRead:
        """Return the calculation, or raise HouseholdCalculationNotFoundError."""
        calculation = self._simulation.read(calculation_id)
        if calculation is None:
            msg = f"Household calculation {calculation_id} not found."
            raise HouseholdCalculationNotFoundError(msg)
        return HouseholdCalculationRead.from_simulation(calculation)
