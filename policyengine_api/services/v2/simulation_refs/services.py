"""Check v2 report and simulation references with the simulation service.

Reports and simulations live in the Simulation Entrypoint's database, so the
v2 tables that save them keep no foreign key to them. Before a v2 ID is
saved, the entrypoint is asked whether that record exists in the country.
The check runs before the caller opens its v2 transaction. A report ID that
is not one of the country's economy reports may be one of its household
reports, which the entrypoint serves through other routes.
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

    from policyengine_api.services.v2.household_reports.types import (
        HouseholdReportSimulation,
    )
    from policyengine_api.services.v2.simulation_entrypoint.types import (
        EconomyReportRecord,
        EconomyReportSimulation,
        SimulationRecord,
    )


class SimulationReferenceService:
    """Existence checks of v2 reports and simulations with the entrypoint."""

    def __init__(
        self,
        simulation: EconomyReportSimulation,
        *,
        household_reports: HouseholdReportSimulation | None = None,
    ) -> None:
        """Read economy reports and simulations through ``simulation``.

        With ``household_reports``, a report ID that is not one of the
        country's economy reports is also looked for among its household
        reports.
        """
        self._simulation = simulation
        self._household_reports = household_reports

    @property
    def checks_household_reports(self) -> bool:
        """Whether a saved report may name a household report."""
        return self._household_reports is not None

    def _household_report_country(self, report_id: UUID) -> str | None:
        """Return a household report's country, or None without one."""
        if self._household_reports is None:
            return None
        try:
            return self._household_reports.get_report(report_id).country_id
        except SimulationRecordNotFoundError:
            return None

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
        if report is None or report.country_id != country_id:
            # A household report is never migrated from a v1 report output.
            require_reference_in_country(
                self._household_report_country(report_id),
                kind="report",
                reference_id=report_id,
                country_id=country_id,
            )
            found_legacy_id = None
        else:
            found_legacy_id = report.legacy_report_id
        require_migrated_from(
            found_legacy_id,
            kind="report",
            record_id=report_id,
            legacy_id=legacy_report_id,
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
        if found_country_id != country_id:
            found_country_id = self._household_report_country(report_id)
        require_reference_in_country(
            found_country_id,
            kind="report",
            reference_id=report_id,
            country_id=country_id,
        )

    def require_simulation(
        self,
        *,
        country_id: str,
        simulation_id: UUID,
        legacy_simulation_id: int | None = None,
    ) -> None:
        """Raise ``SimulationReferenceNotFoundError`` unless the country has it.

        With ``legacy_simulation_id``, also raise
        ``AssociationReferenceConflictError`` unless the simulation was
        migrated from that v1 simulation.
        """
        try:
            simulation: SimulationRecord | None = self._simulation.get_simulation(
                simulation_id
            )
        except SimulationRecordNotFoundError:
            simulation = None
        require_reference_in_country(
            None if simulation is None else simulation.country_id,
            kind="simulation",
            reference_id=simulation_id,
            country_id=country_id,
        )
        if simulation is not None and legacy_simulation_id is not None:
            require_migrated_from(
                simulation.legacy_simulation_id,
                kind="simulation",
                record_id=simulation_id,
                legacy_id=legacy_simulation_id,
            )
