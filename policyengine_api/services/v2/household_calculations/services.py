"""Calculate stored households through the simulation service, and read the results.

Submitting a calculation checks, in order, that the country's ``countries``
row allows household calculations (a household-only country does), that the
stored household and policy exist in that country, through the same
services as ``/v2/households`` and ``/v2/policies`` (so one of another
country, or none, is not found), that the household has a default year, and
that the policy sets no parameter the running catalog version lacks. Only
then does it send the simulation service the IDs and options. The simulation
service reads the household, the policy's parameter values and the catalog
version from the Public API's tables itself, inserts the job and calculates
the household's default year; each submission creates a new job.

Reading a calculation reads its job from ``household_jobs``, which the
simulation service inserts and its household function completes; it never
calls the simulation service.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

from policyengine_api.services.v2.household_calculations.database_connectors import (
    reads as household_job_reads,
)
from policyengine_api.services.v2.household_calculations.transformations import (
    household_calculation_read,
    household_calculation_submitted,
)
from policyengine_api.services.v2.household_calculations.validators import (
    HouseholdCalculationNotFoundError,
    HouseholdCalculationStorageError,
    require_default_year,
    require_household_country,
    stored_household_outcome,
)
from policyengine_api.services.v2.policies.validators import (
    require_policy_parameters_present,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from uuid import UUID

    from policyengine_api.services.v2.household_calculations.database_session import (
        HouseholdCalculationDatabaseSession,
    )
    from policyengine_api.services.v2.household_calculations.types import (
        CountrySource,
        HouseholdCalculationInput,
        HouseholdCalculationRead,
        HouseholdCalculationSubmitted,
        HouseholdCalculationSubmitter,
        HouseholdSource,
        PolicySource,
    )


@contextmanager
def _storage_failures() -> Iterator[None]:
    """Raise HouseholdCalculationStorageError for a failed database read."""
    try:
        yield
    except SQLAlchemyError as error:
        msg = "V2 household calculation storage is unavailable"
        raise HouseholdCalculationStorageError(msg) from error


class V2HouseholdCalculationService:
    """Submit household calculations to the simulation service and read them."""

    def __init__(
        self,
        *,
        countries: CountrySource,
        households: HouseholdSource,
        policies: PolicySource,
        database_session: HouseholdCalculationDatabaseSession,
        simulation_factory: Callable[[], HouseholdCalculationSubmitter],
    ) -> None:
        """Read through these services and sessions for one request.

        ``simulation_factory`` returns the simulation service's client only
        once a submission is sent to it, so a request the Public API refuses
        gets its own answer even when the simulation service is not
        configured, and a read never needs it.
        """
        self._countries = countries
        self._households = households
        self._policies = policies
        self._database_session = database_session
        self._simulation_factory = simulation_factory

    def submit_calculation(
        self, calculation: HouseholdCalculationInput
    ) -> HouseholdCalculationSubmitted:
        """Send the calculation to the simulation service and return its new job.

        Raise HouseholdCalculationCountryError, HouseholdNotFoundError,
        PolicyNotFoundError, HouseholdCalculationYearError or
        PolicyParametersMissingError, in that order, before anything is sent;
        HouseholdCalculationStorageError when the database cannot be read;
        and the simulation service's errors when it refuses the calculation.
        """
        country_id = calculation.country_id
        with _storage_failures():
            require_household_country(self._countries.list_countries(), country_id)
            household = self._households.get_household(
                country_id=country_id, household_id=calculation.household_id
            )
            policy = (
                None
                if calculation.policy_id is None
                else self._policies.get_policy(
                    country_id=country_id, policy_id=calculation.policy_id
                )
            )
        year = require_default_year(household.default_year)
        if policy is not None:
            require_policy_parameters_present(policy.id, policy.missing_parameters)
        accepted = self._simulation_factory().submit(calculation)
        return household_calculation_submitted(calculation, accepted, year=year)

    def get_calculation(self, calculation_id: UUID) -> HouseholdCalculationRead:
        """Return the calculation household_jobs records.

        Raise HouseholdCalculationNotFoundError when there is no such job,
        HouseholdCalculationResultUnreadableError when a succeeded job's
        result cannot be read, and HouseholdCalculationStorageError when the
        database cannot be read.
        """
        with _storage_failures(), self._database_session.read() as session:
            job = household_job_reads.read_household_job(session, calculation_id)
            if job is None:
                msg = f"Household calculation {calculation_id} not found."
                raise HouseholdCalculationNotFoundError(msg)
            return household_calculation_read(
                job, stored_household_outcome(job.id, job.status, job.result)
            )
