"""Convert stored simulation rows to the reads the simulation read service returns."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.stored_simulations.types import (
    SimulationRead,
    SimulationRunRead,
)

if TYPE_CHECKING:
    from policyengine_api.data.v2.models import SimulationRun
    from policyengine_api.services.v2.simulation_service.types import (
        PackageVersions,
    )
    from policyengine_api.services.v2.stored_simulations.types import (
        StoredSimulationRows,
    )


def simulation_run_read(run: SimulationRun) -> SimulationRunRead:
    """Return the run's year, status, versions and times."""
    return SimulationRunRead(
        id=run.id,
        year=run.year,
        status=run.status.value,
        country_package_version=run.country_package_version,
        policyengine_version=run.policyengine_version,
        error_message=run.error_message,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


def simulation_read(
    rows: StoredSimulationRows,
    *,
    country_id: str,
    current_versions: PackageVersions,
) -> SimulationRead:
    """Return a simulation's definition and newest run in its country."""
    simulation = rows.simulation
    run = rows.newest_run
    return SimulationRead(
        id=simulation.id,
        country_id=country_id,
        kind=simulation.simulation_type.value,
        policy_id=simulation.policy_id,
        dynamic_id=simulation.dynamic_id,
        household_id=simulation.household_id,
        year=simulation.year,
        region_code=rows.region_code,
        dataset_name=rows.dataset_name,
        created_at=simulation.created_at,
        status="not_run" if run is None else run.status.value,
        run=None if run is None else simulation_run_read(run),
        current_versions=current_versions,
    )
