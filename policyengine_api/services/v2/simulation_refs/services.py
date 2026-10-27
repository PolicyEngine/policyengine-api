"""Check v2 report and simulation references with the simulation service.

Reports and simulations live in the Simulation Entrypoint's database, so the
v2 tables that save them keep no foreign key to them. Before a v2 ID is
saved, the entrypoint is asked whether that record exists in the country.
The check runs before the caller opens its v2 transaction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.simulation_entrypoint.types import (
    SimulationRecordNotFoundError,
)
from policyengine_api.services.v2.simulation_refs.validators import (
    require_reference_in_country,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from policyengine_api.services.v2.associations.types import (
        SimulationReferenceChecker,
    )
    from policyengine_api.services.v2.simulation_entrypoint.types import (
        EconomyReportSimulation,
    )


class SimulationReferenceService:
    """Existence checks of v2 reports and simulations, one entrypoint read each."""

    def __init__(self, simulation: EconomyReportSimulation) -> None:
        """Read reports and simulations through ``simulation``."""
        self._simulation = simulation

    def require_report(self, *, country_id: str, report_id: UUID) -> None:
        """Raise ``SimulationReferenceNotFoundError`` unless the country has it."""
        try:
            found_country_id: str | None = self._simulation.get_report(
                report_id
            ).country_id
        except SimulationRecordNotFoundError:
            found_country_id = None
        require_reference_in_country(
            found_country_id,
            kind="report",
            reference_id=report_id,
            country_id=country_id,
        )

    def require_simulation(self, *, country_id: str, simulation_id: UUID) -> None:
        """Raise ``SimulationReferenceNotFoundError`` unless the country has it."""
        try:
            found_country_id: str | None = self._simulation.get_simulation(
                simulation_id
            ).country_id
        except SimulationRecordNotFoundError:
            found_country_id = None
        require_reference_in_country(
            found_country_id,
            kind="simulation",
            reference_id=simulation_id,
            country_id=country_id,
        )


class DeferredSimulationReferenceService:
    """Build the reference service only when a v2 reference is checked.

    Most saved-record routes never check one, so they must not depend on the
    simulation client or the entrypoint's configuration.
    """

    def __init__(self, build: Callable[[], SimulationReferenceChecker]) -> None:
        """Call ``build`` at the first check and reuse its service afterwards."""
        self._build = build
        self._service: SimulationReferenceChecker | None = None

    def _resolved(self) -> SimulationReferenceChecker:
        if self._service is None:
            self._service = self._build()
        return self._service

    def require_report(self, *, country_id: str, report_id: UUID) -> None:
        """Raise ``SimulationReferenceNotFoundError`` unless the country has it."""
        self._resolved().require_report(country_id=country_id, report_id=report_id)

    def require_simulation(self, *, country_id: str, simulation_id: UUID) -> None:
        """Raise ``SimulationReferenceNotFoundError`` unless the country has it."""
        self._resolved().require_simulation(
            country_id=country_id, simulation_id=simulation_id
        )
