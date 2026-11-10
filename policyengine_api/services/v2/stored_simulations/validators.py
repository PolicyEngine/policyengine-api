"""Database-independent checks of v2 simulations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.services.v2.stored_simulations.types import (
        StoredSimulationRows,
    )


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
