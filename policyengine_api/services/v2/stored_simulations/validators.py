"""Database-independent checks of v2 simulations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.services.v2.stored_simulations.types import (
        StoredSimulationRows,
    )


class CreatedSimulationUnreadableError(RuntimeError):
    """The simulation service created the simulation, but it could not be read back.

    The simulation service answered with the simulation's ID, so the
    simulation exists and submitting it again would create another.
    ``simulation_id`` and ``country_id`` say where to read it; the error's
    cause says why reading it back failed.
    """

    def __init__(self, *, simulation_id: UUID, country_id: str) -> None:
        """Name the created simulation and its country."""
        super().__init__(
            f"The simulation service created simulation {simulation_id} in "
            f"country {country_id!r}, but it could not be read back"
        )
        self.simulation_id = simulation_id
        self.country_id = country_id


class StoredSimulationNotFoundError(LookupError):
    """No simulation of the country's model has this ID."""


class SimulationStorageError(RuntimeError):
    """The detailed-save database could not be read."""


def require_simulation(
    rows: StoredSimulationRows | None, *, simulation_id: UUID, country_id: str
) -> StoredSimulationRows:
    """Return the simulation's rows, or raise StoredSimulationNotFoundError."""
    if rows is None:
        msg = f"Simulation {simulation_id} was not found in country {country_id!r}"
        raise StoredSimulationNotFoundError(msg)
    return rows
