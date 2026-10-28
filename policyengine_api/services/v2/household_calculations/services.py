"""Calculate stored households through the simulation service, and read them.

Submitting a calculation checks the country's ``countries`` row allows
household calculations (a household-only country does), checks the stored
household and policy exist in that country through the same services as
``/v2/households`` and ``/v2/policies`` (so one of another country, or none,
is not found), selects the country's running catalog version, and sends the
simulation service their IDs and that version's PolicyEngine.py version.
The simulation service reads the household, the policy's parameter values
and the catalog version from the Public API's tables itself, and calculates
the household's default year. It records every calculation, so one not
saved to an account is still stored, as a simulation run with no report.

Reading a calculation asks the simulation service for it as it stands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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


def _axes_in_year(
    calculation: HouseholdCalculationInput, year: int
) -> list[list[dict[str, Any]]] | None:
    """Return the axes as sent, each without a period varying ``year``.

    The country model would otherwise vary its own default period, the
    current year, rather than the year the household's values name.
    """
    if calculation.axes is None:
        return None
    sent_axes = []
    for group in calculation.axes:
        sent_group = []
        for axis in group:
            sent_axis = axis.model_dump(mode="json", exclude_unset=True)
            if sent_axis.get("period") is None:
                sent_axis["period"] = str(year)
            sent_group.append(sent_axis)
        sent_axes.append(sent_group)
    return sent_axes


class V2HouseholdCalculationService:
    """Submit household calculations to the simulation service and read them."""

    def __init__(
        self,
        *,
        countries: CountrySource,
        households: HouseholdSource,
        policies: PolicySource,
        catalog_reader_factory: Callable[[], CatalogSource],
        simulation_factory: Callable[[], SimulationHouseholdCalculations],
    ) -> None:
        """Read through these services for one request.

        ``catalog_reader_factory`` opens a catalog reader, with its own
        database session, only once a submission needs the catalog version.
        ``simulation_factory`` returns the simulation service's client only
        once a request is sent to it, so a request the Public API refuses
        gets its own answer even when the simulation service is not
        configured.
        """
        self._countries = countries
        self._households = households
        self._policies = policies
        self._catalog_reader_factory = catalog_reader_factory
        self._simulation_factory = simulation_factory

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
        if calculation.policy_id is not None:
            self._policies.get_policy(
                country_id=country_id, policy_id=calculation.policy_id
            )
        year = calculation_year(household.default_year)
        catalog_reader = self._catalog_reader_factory()
        try:
            catalog = catalog_reader.get_model_by_country(country_id)
        finally:
            catalog_reader.close()
        submission: dict[str, Any] = {
            "country": country_id,
            "policyengine_version": catalog.policyengine_version,
            "household_id": str(household.id),
            "policy_id": (
                None if calculation.policy_id is None else str(calculation.policy_id)
            ),
            "options": {
                "axes": _axes_in_year(calculation, year),
                "add_missing_variables": calculation.add_missing_variables,
            },
            # A calculation is reused for 28 days after it succeeded; callers
            # without an account must not start new Modal calls at will.
            "force": False,
            "trigger": "initial",
        }
        return HouseholdCalculationRead.from_simulation(
            self._simulation_factory().submit(submission)
        )

    def get_calculation(self, calculation_id: UUID) -> HouseholdCalculationRead:
        """Return the calculation, or raise HouseholdCalculationNotFoundError."""
        calculation = self._simulation_factory().read(calculation_id)
        if calculation is None:
            msg = f"Household calculation {calculation_id} not found."
            raise HouseholdCalculationNotFoundError(msg)
        return HouseholdCalculationRead.from_simulation(calculation)
