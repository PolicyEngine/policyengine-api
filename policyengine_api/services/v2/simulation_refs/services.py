"""Check v2 report and simulation references with the simulation service.

Reports and simulations live in the Simulation Entrypoint's database, so the
v2 tables that save them keep no foreign key to them. Before a v2 ID is
saved, the entrypoint is asked whether that record exists in the country.
The check runs before the caller opens its v2 transaction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.simulation_entrypoint.services import (
    read_report_country,
)
from policyengine_api.services.v2.simulation_entrypoint.types import (
    SimulationRecordNotFoundError,
)
from policyengine_api.services.v2.simulation_refs.validators import (
    require_migrated_from,
    require_reference_in_country,
)

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.services.v2.simulation_entrypoint.types import (
        EconomyReportRecord,
        EconomyReportSimulation,
    )


class SimulationReferenceService:
    """Existence checks of v2 reports and simulations, one entrypoint read each."""

    def __init__(self, simulation: EconomyReportSimulation) -> None:
        """Read reports and simulations through ``simulation``."""
        self._simulation = simulation

    def require_report(
        self,
        *,
        country_id: str,
        report_id: UUID,
        legacy_report_id: int | None = None,
    ) -> None:
        """Raise ``SimulationReferenceNotFoundError`` unless the country has it.

        With ``legacy_report_id``, also raise
        ``AssociationReferenceConflictError`` unless the report was migrated
        from that v1 report output; that check reads the whole report. Without
        it, the country is read from the report's simulations, so a report
        whose stored result cannot be read back can still be saved.
        """
        if legacy_report_id is None:
            self._require_report_country(country_id=country_id, report_id=report_id)
            return
        try:
            report: EconomyReportRecord | None = self._simulation.get_report(report_id)
        except SimulationRecordNotFoundError:
            report = None
        require_reference_in_country(
            None if report is None else report.country_id,
            kind="report",
            reference_id=report_id,
            country_id=country_id,
        )
        if report is not None:
            require_migrated_from(
                report.legacy_report_id,
                report_id=report_id,
                legacy_report_id=legacy_report_id,
            )

    def _require_report_country(self, *, country_id: str, report_id: UUID) -> None:
        try:
            found_country_id: str | None = read_report_country(
                self._simulation,
                report_id,
                self._simulation.list_report_runs(report_id),
            )
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
