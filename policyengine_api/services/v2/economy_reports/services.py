"""Application services for v2 economy reports.

The Simulation Entrypoint owns economy reports. This service checks what the
Public API decides itself, then asks the entrypoint through
``EconomyReportSimulation``:

- A country's ``countries`` row must allow economy (society-wide) reports. A
  household-only country is refused before anything is sent to the
  entrypoint, and the Public API writes nothing for a report.
- Reports run on the current catalog version: the one published for the
  PolicyEngine.py version the Public API runs, which is also the catalog its
  v2 metadata routes serve by default.
- Every report is read within a country: a report of another country is not
  found.
- A report with no run (one migrated from v1) is calculated the first time
  it is read: reading it starts a run with the ``system`` trigger.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from policyengine_api.services.v2.economy_reports.database_connectors.reads import (
    read_country,
)
from policyengine_api.services.v2.economy_reports.transformations import (
    economy_report_submission,
    reports_of_country,
)
from policyengine_api.services.v2.economy_reports.validators import (
    economy_reports_supported,
    report_not_found,
    require_economy_reports_supported,
    require_report_in_country,
)
from policyengine_api.services.v2.simulation_entrypoint.types import (
    RunTrigger,
    SimulationRecordNotFoundError,
    SimulationRequestRefusedError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from uuid import UUID

    from policyengine_api.services.v2.economy_reports.database_session import (
        EconomyReportDatabaseSession,
    )
    from policyengine_api.services.v2.economy_reports.types import EconomyReportFields
    from policyengine_api.services.v2.simulation_entrypoint.types import (
        EconomyReportRecord,
        EconomyReportRunRecord,
        EconomyReportSimulation,
    )

logger = logging.getLogger(__name__)


class V2EconomyReportService:
    """Sequence economy report operations between the countries table and sim."""

    def __init__(
        self,
        database_session: EconomyReportDatabaseSession,
        simulation: EconomyReportSimulation,
        *,
        current_policyengine_version: str,
    ) -> None:
        """Read countries through ``database_session``, reports through ``simulation``.

        ``current_policyengine_version`` selects the catalog version new runs use.
        """
        self._database_session = database_session
        self._simulation = simulation
        self._current_policyengine_version = current_policyengine_version

    def _require_economy_reports(self, country_id: str) -> None:
        with self._database_session.read() as session:
            country = read_country(session, country_id)
        require_economy_reports_supported(country, country_id=country_id)

    def submit_report(
        self, *, country_id: str, report_input: EconomyReportFields
    ) -> EconomyReportRecord:
        """Create a report, its simulations and its first run in the entrypoint.

        Raise ``EconomyReportsUnsupportedError`` for a country without economy
        reports, before the entrypoint is asked, and
        ``SimulationRequestRefusedError`` when the entrypoint cannot run it.
        """
        self._require_economy_reports(country_id)
        return self._simulation.submit_report(
            economy_report_submission(
                report_input,
                country_id=country_id,
                policyengine_version=self._current_policyengine_version,
            )
        )

    def _report_in_country(
        self,
        read: Callable[[], EconomyReportRecord],
        *,
        country_id: str,
        reference: str,
    ) -> EconomyReportRecord:
        try:
            report: EconomyReportRecord | None = read()
        except SimulationRecordNotFoundError:
            report = None
        return require_report_in_country(
            report, country_id=country_id, reference=reference
        )

    def _start_first_run(self, report: EconomyReportRecord) -> EconomyReportRecord:
        """Start the first run of a report that has none, and read it again.

        A migrated report has no run until it is first read. Its country must
        still have economy reports, and a run the entrypoint refuses (for
        example, a region the current catalog version lacks) leaves it not run.
        """
        if report.run is not None:
            return report
        with self._database_session.read() as session:
            country = read_country(session, report.country_id)
        if not economy_reports_supported(country):
            return report
        try:
            self._simulation.run_report(
                report.id,
                policyengine_version=self._current_policyengine_version,
                trigger=RunTrigger.SYSTEM,
                force=False,
            )
        except SimulationRecordNotFoundError as error:
            raise report_not_found(
                country_id=report.country_id, reference=str(report.id)
            ) from error
        except SimulationRequestRefusedError as error:
            logger.warning(
                "v2_economy_report_first_run_refused",
                extra={
                    "policyengine_attributes": {
                        "report_id": str(report.id),
                        "reason": str(error)[:500],
                    }
                },
            )
            return report
        return self._report_in_country(
            lambda: self._simulation.get_report(report.id),
            country_id=report.country_id,
            reference=str(report.id),
        )

    def get_report(self, *, country_id: str, report_id: UUID) -> EconomyReportRecord:
        """Return a report of this country, starting its first run if it has none.

        Raise ``EconomyReportNotFoundError`` when the entrypoint has no such
        report in this country.
        """
        return self._start_first_run(
            self._report_in_country(
                lambda: self._simulation.get_report(report_id),
                country_id=country_id,
                reference=str(report_id),
            )
        )

    def get_report_by_legacy_number(
        self, *, country_id: str, legacy_report_id: int
    ) -> EconomyReportRecord:
        """Return the report migrated from a v1 report output number.

        Like ``get_report``, its first run starts if it has none. Raise
        ``EconomyReportNotFoundError`` when no report of this country was
        migrated from that number.
        """
        return self._start_first_run(
            self._report_in_country(
                lambda: self._simulation.get_report_by_legacy_id(legacy_report_id),
                country_id=country_id,
                reference=f"migrated from v1 report {legacy_report_id}",
            )
        )

    def run_report(
        self, *, country_id: str, report_id: UUID, force: bool
    ) -> EconomyReportRunRecord:
        """Run a report of the country again on the current catalog version.

        The run has the ``manual`` trigger and reuses existing simulation runs
        unless ``force`` is set. Raise ``EconomyReportsUnsupportedError`` for a
        country without economy reports, before the entrypoint is asked,
        ``EconomyReportNotFoundError`` when the country has no such report, and
        ``SimulationRequestRefusedError`` when the entrypoint cannot run it.
        """
        self._require_economy_reports(country_id)
        reference = str(report_id)
        self._report_in_country(
            lambda: self._simulation.get_report(report_id),
            country_id=country_id,
            reference=reference,
        )
        try:
            return self._simulation.run_report(
                report_id,
                policyengine_version=self._current_policyengine_version,
                trigger=RunTrigger.MANUAL,
                force=force,
            )
        except SimulationRecordNotFoundError as error:
            raise report_not_found(
                country_id=country_id, reference=reference
            ) from error

    def list_report_runs(
        self, *, country_id: str, report_id: UUID
    ) -> tuple[EconomyReportRunRecord, ...]:
        """Return a report's runs, newest first, each with its catalog version.

        Raise ``EconomyReportNotFoundError`` when the country has no such report.
        """
        reference = str(report_id)
        self._report_in_country(
            lambda: self._simulation.get_report(report_id),
            country_id=country_id,
            reference=reference,
        )
        try:
            return self._simulation.list_report_runs(report_id)
        except SimulationRecordNotFoundError as error:
            raise report_not_found(
                country_id=country_id, reference=reference
            ) from error

    def _report_or_none(self, report_id: UUID) -> EconomyReportRecord | None:
        try:
            return self._simulation.get_report(report_id)
        except SimulationRecordNotFoundError:
            return None

    def list_reports(
        self, *, country_id: str, report_ids: Sequence[UUID]
    ) -> tuple[EconomyReportRecord, ...]:
        """Return the country's reports among ``report_ids``, in that order, once each.

        Unknown reports and other countries' are left out. Listing a report
        with no run does not start one; reading it does.
        """
        return reports_of_country(
            (
                self._report_or_none(report_id)
                for report_id in dict.fromkeys(report_ids)
            ),
            country_id=country_id,
        )
