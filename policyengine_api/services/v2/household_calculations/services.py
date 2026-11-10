"""Calculate stored households through the simulation service, and read the results.

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
)
from policyengine_api.services.v2.household_calculations.validators import (
    HouseholdCalculationNotFoundError,
    HouseholdCalculationStorageError,
    stored_household_outcome,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from uuid import UUID

    from policyengine_api.services.v2.household_calculations.database_session import (
        HouseholdCalculationDatabaseSession,
    )
    from policyengine_api.services.v2.household_calculations.types import (
        CountrySource,
        HouseholdCalculationRead,
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
