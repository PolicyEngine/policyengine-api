"""Build the Simulation Entrypoint adapter only when it is first needed."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from policyengine_api.services.v2.simulation_entrypoint.types import (
        EconomyReportRecord,
        EconomyReportRunRecord,
        EconomyReportSimulation,
        EconomyReportSubmission,
        RunTrigger,
        SimulationRecord,
    )


class DeferredEconomyReportSimulation:
    """``EconomyReportSimulation`` that builds its adapter at its first call.

    The Public API decides some refusals itself, such as a household-only
    country's economy report, and those must not depend on the simulation
    client or its settings. A build that raises
    ``SimulationServiceUnavailableError`` is tried again at the next call.
    """

    def __init__(self, build: Callable[[], EconomyReportSimulation]) -> None:
        """Call ``build`` at the first call and reuse its adapter afterwards."""
        self._build = build
        self._simulation: EconomyReportSimulation | None = None

    def _resolved(self) -> EconomyReportSimulation:
        if self._simulation is None:
            self._simulation = self._build()
        return self._simulation

    def submit_report(self, submission: EconomyReportSubmission) -> EconomyReportRecord:
        """Create a report and its first run in the entrypoint, and start it."""
        return self._resolved().submit_report(submission)

    def get_report(self, report_id: UUID) -> EconomyReportRecord:
        """Return a report."""
        return self._resolved().get_report(report_id)

    def get_report_by_legacy_id(self, legacy_report_id: int) -> EconomyReportRecord:
        """Return the report migrated from a v1 report output number."""
        return self._resolved().get_report_by_legacy_id(legacy_report_id)

    def run_report(
        self,
        report_id: UUID,
        *,
        policyengine_version: str,
        trigger: RunTrigger,
        force: bool,
    ) -> EconomyReportRunRecord:
        """Run a report again on the catalog version of ``policyengine_version``."""
        return self._resolved().run_report(
            report_id,
            policyengine_version=policyengine_version,
            trigger=trigger,
            force=force,
        )

    def list_report_runs(self, report_id: UUID) -> tuple[EconomyReportRunRecord, ...]:
        """Return a report's runs, newest first."""
        return self._resolved().list_report_runs(report_id)

    def get_simulation(self, simulation_id: UUID) -> SimulationRecord:
        """Return a simulation."""
        return self._resolved().get_simulation(simulation_id)
