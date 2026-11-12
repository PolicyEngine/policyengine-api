"""Framework-independent data exchanged by the v2 simulation layers.

A simulation applies a policy and dynamic to one household or one dataset;
each calculation of it, for one year on one PolicyEngine.py version, is a
simulation run. The simulation service creates both; the Public API reads
them directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from policyengine_api.data.v2.models import Simulation, SimulationRun
    from policyengine_api.services.v2.simulation_service.types import (
        PackageVersions,
    )

SimulationKind = Literal["economy", "household"]
# A simulation's status is its newest run's, or not_run while it has none.
SimulationStatusName = Literal["not_run", "pending", "running", "succeeded", "failed"]


@dataclass(frozen=True)
class SimulationRunRead:
    """One calculation of a simulation, for one year on one package version pair."""

    id: UUID
    year: int
    status: Literal["pending", "running", "succeeded", "failed"]
    country_package_version: str
    policyengine_version: str
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True)
class SimulationRead:
    """A simulation's definition, its newest run and the versions the Public API runs.

    ``policy_id`` and ``dynamic_id`` are null for current law. An economy
    simulation names its region and dataset, a household simulation its
    household. ``current_versions`` are the versions the Public API serves
    now; a newest run on other versions is out of date.
    """

    id: UUID
    country_id: str
    kind: SimulationKind
    policy_id: UUID | None
    dynamic_id: UUID | None
    household_id: UUID | None
    year: int | None
    region_code: str | None
    dataset_name: str | None
    created_at: datetime
    status: SimulationStatusName
    run: SimulationRunRead | None
    current_versions: PackageVersions


@dataclass(frozen=True)
class StoredSimulationRows:
    """A simulation's row, its region's code, its dataset's name and its newest run.

    ``newest_run`` is the run created last, whatever its year, status and
    versions, or None.
    """

    simulation: Simulation
    region_code: str | None
    dataset_name: str | None
    newest_run: SimulationRun | None
