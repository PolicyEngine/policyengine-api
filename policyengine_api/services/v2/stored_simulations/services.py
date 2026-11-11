"""Create economy simulations through the simulation service, and read simulations.

A simulation is read within the country whose model its catalog version
belongs to, with its newest run: the run created last, whatever its year,
status and versions, beside the versions the Public API runs now. Results
are not part of it: an economy run's output is a file, and a household
run's result is read with household reports.

Creating a simulation checks the country and its policy, asks the
simulation service to create and start it, then reads it back. Once the
simulation service has answered with the simulation's ID, the simulation
exists: a failure to read it back raises CreatedSimulationUnreadableError,
which names it, so the caller reads it rather than submitting it again.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

from policyengine_api.services.v2.simulation_service.types import (
    SimulationServiceUnavailableError,
)
from policyengine_api.services.v2.stored_simulations.database_connectors.reads import (
    read_simulation_rows,
)
from policyengine_api.services.v2.stored_simulations.transformations import (
    simulation_read,
)
from policyengine_api.services.v2.stored_simulations.validators import (
    CreatedSimulationUnreadableError,
    SimulationStorageError,
    require_simulation,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from uuid import UUID

    from policyengine_api.services.v2.simulation_service.types import (
        EconomySimulationCreationInput,
        PackageVersions,
        SimulationServiceClient,
    )
    from policyengine_api.services.v2.stored_simulations.database_session import (
        StoredSimulationDatabaseSession,
    )
    from policyengine_api.services.v2.stored_simulations.types import SimulationRead


class SimulationSubmissionsNotConfiguredError(SimulationServiceUnavailableError):
    """The service was built without a way to submit to the simulation service."""


@contextmanager
def _storage_failures() -> Iterator[None]:
    """Raise SimulationStorageError for a failed database read."""
    try:
        yield
    except SQLAlchemyError as error:
        msg = "V2 simulation storage is unavailable"
        raise SimulationStorageError(msg) from error


class V2StoredSimulationService:
    """Read v2 simulations and their newest runs, and create economy simulations."""

    def __init__(
        self,
        database_session: StoredSimulationDatabaseSession,
        *,
        current_versions: Callable[[str], PackageVersions],
        submissions: SimulationServiceClient | None = None,
    ) -> None:
        """Read through ``database_session``; create through ``submissions``.

        ``current_versions`` returns the country package and PolicyEngine.py
        versions the Public API runs for a country. ``submissions`` is the
        checking ``SimulationSubmissionService``; without it, creating a
        simulation raises SimulationSubmissionsNotConfiguredError.
        """
        self._database_session = database_session
        self._current_versions = current_versions
        self._submissions = submissions

    def get_simulation(self, *, country_id: str, simulation_id: UUID) -> SimulationRead:
        """Return the country's simulation and its newest run.

        Raise StoredSimulationNotFoundError when no simulation of the
        country's model has this ID, and SimulationStorageError when the
        database cannot be read.
        """
        with _storage_failures(), self._database_session.read() as session:
            stored = require_simulation(
                read_simulation_rows(
                    session, country_id=country_id, simulation_id=simulation_id
                ),
                simulation_id=simulation_id,
                country_id=country_id,
            )
            return simulation_read(
                stored,
                country_id=country_id,
                current_versions=self._current_versions(country_id),
            )

    def create_simulation(
        self, simulation_input: EconomySimulationCreationInput
    ) -> SimulationRead:
        """Create the simulation through the simulation service; return it as stored.

        Raise the submission's errors (see ``SimulationSubmissionService``),
        and CreatedSimulationUnreadableError, caused by the read's own error,
        when the simulation the simulation service created cannot be read
        back in the country: not stored there, the database unavailable, or
        any other failure of the read.
        """
        if self._submissions is None:
            msg = "The simulation service is not configured here"
            raise SimulationSubmissionsNotConfiguredError(msg)
        submitted = self._submissions.submit_simulation(simulation_input)
        try:
            return self.get_simulation(
                country_id=simulation_input.country_id,
                simulation_id=submitted.simulation_id,
            )
        except Exception as error:
            # The simulation exists whatever failed, so the caller gets its ID.
            raise CreatedSimulationUnreadableError(
                simulation_id=submitted.simulation_id,
                country_id=simulation_input.country_id,
            ) from error
