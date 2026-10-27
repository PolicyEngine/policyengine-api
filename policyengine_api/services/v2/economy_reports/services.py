"""Application services for v2 economy reports.

The Simulation Entrypoint owns economy reports. This service checks what API
v1 decides itself, then asks the entrypoint through ``EconomyReportSimulation``:

- A country's ``countries`` row must allow economy (society-wide) reports. A
  household-only country is refused before anything is sent to the
  entrypoint, and API v1 writes nothing for a report.
- Reports run on the current catalog version: the one published for the
  PolicyEngine.py version API v1 runs, which is also the catalog its v2
  metadata routes serve by default.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.economy_reports.database_connectors.reads import (
    read_country,
)
from policyengine_api.services.v2.economy_reports.transformations import (
    economy_report_submission,
)
from policyengine_api.services.v2.economy_reports.validators import (
    require_economy_reports_supported,
)

if TYPE_CHECKING:
    from policyengine_api.services.v2.economy_reports.database_session import (
        EconomyReportDatabaseSession,
    )
    from policyengine_api.services.v2.economy_reports.types import (
        EconomyReportFields,
        EconomyReportRecord,
        EconomyReportSimulation,
    )


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
