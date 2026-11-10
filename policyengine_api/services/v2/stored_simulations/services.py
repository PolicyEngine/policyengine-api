"""Read v2 simulations, each with its newest run.

A simulation is read within the country whose model its catalog version
belongs to, with its newest run: the run created last, whatever its year,
status and versions, beside the versions the Public API runs now. Results
are not part of it: an economy run's output is a file, and a household
run's result is read with household reports.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

from policyengine_api.services.v2.stored_simulations.database_connectors.reads import (
    read_simulation_rows,
)
from policyengine_api.services.v2.stored_simulations.transformations import (
    simulation_read,
)
from policyengine_api.services.v2.stored_simulations.validators import (
    SimulationStorageError,
    require_simulation,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from uuid import UUID

    from policyengine_api.services.v2.simulation_service.types import (
        PackageVersions,
    )
    from policyengine_api.services.v2.stored_simulations.database_session import (
        StoredSimulationDatabaseSession,
    )
    from policyengine_api.services.v2.stored_simulations.types import SimulationRead


@contextmanager
def _storage_failures() -> Iterator[None]:
    """Raise SimulationStorageError for a failed database read."""
    try:
        yield
    except SQLAlchemyError as error:
        msg = "V2 simulation storage is unavailable"
        raise SimulationStorageError(msg) from error


class V2StoredSimulationService:
    """Read v2 simulations and their newest runs."""

    def __init__(
        self,
        database_session: StoredSimulationDatabaseSession,
        *,
        current_versions: Callable[[str], PackageVersions],
    ) -> None:
        """Read through ``database_session``.

        ``current_versions`` returns the country package and PolicyEngine.py
        versions the Public API runs for a country.
        """
        self._database_session = database_session
        self._current_versions = current_versions

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
