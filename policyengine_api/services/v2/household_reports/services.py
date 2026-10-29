"""Application services for v2 household reports.

The Simulation Entrypoint owns household reports and reads the stored
household and policies from the Public API's tables itself. Before asking
it, this service checks what the Public API decides, through the same
services as ``/v2/households`` and ``/v2/policies``:

- A country's ``countries`` row must allow household calculations; a
  household-only country does.
- The household, and each policy a report names, must be stored for the
  country; one of another country, or none, is not found.
- The household must have a default year, the year the report calculates.

Reports run on the current catalog version: the one published for the
PolicyEngine.py version the Public API runs, as economy reports do. A run's
PolicyEngine.py version is read from the Public API's own catalog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.household_reports.database_connectors.reads import (
    read_country,
    read_policyengine_versions,
)
from policyengine_api.services.v2.household_reports.transformations import (
    household_report_submission,
    run_catalog_version_ids,
    with_policyengine_version,
)
from policyengine_api.services.v2.household_reports.validators import (
    require_default_year,
    require_household_reports_supported,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from policyengine_api.services.v2.household_reports.database_session import (
        HouseholdReportDatabaseSession,
    )
    from policyengine_api.services.v2.household_reports.types import (
        HouseholdReportFields,
        HouseholdReportRecord,
        HouseholdReportSimulation,
        HouseholdReportSubmission,
        HouseholdSource,
        PolicySource,
    )
    from policyengine_api.services.v2.simulation_entrypoint.types import RunTrigger


class DeferredHouseholdReportSimulation:
    """``HouseholdReportSimulation`` that builds its adapter at its first call.

    The Public API decides some refusals itself, such as a country without
    household calculations or an unknown household, and those must not depend
    on the simulation client or its settings. A build that raises
    ``SimulationServiceUnavailableError`` is tried again at the next call.
    """

    def __init__(self, build: Callable[[], HouseholdReportSimulation]) -> None:
        """Call ``build`` at the first call and reuse its adapter afterwards."""
        self._build = build
        self._simulation: HouseholdReportSimulation | None = None

    def _resolved(self) -> HouseholdReportSimulation:
        if self._simulation is None:
            self._simulation = self._build()
        return self._simulation

    def submit_report(
        self, submission: HouseholdReportSubmission
    ) -> HouseholdReportRecord:
        """Create a report and its first run in the entrypoint, and start it."""
        return self._resolved().submit_report(submission)

    def get_report(self, report_id: UUID) -> HouseholdReportRecord:
        """Return a report."""
        return self._resolved().get_report(report_id)

    def run_report(
        self,
        report_id: UUID,
        *,
        policyengine_version: str,
        trigger: RunTrigger,
        force: bool,
    ) -> HouseholdReportRecord:
        """Start another run of a report on the catalog version of a version."""
        return self._resolved().run_report(
            report_id,
            policyengine_version=policyengine_version,
            trigger=trigger,
            force=force,
        )


class V2HouseholdReportService:
    """Sequence household report operations between the v2 tables and sim."""

    def __init__(
        self,
        database_session: HouseholdReportDatabaseSession,
        *,
        households: HouseholdSource,
        policies: PolicySource,
        simulation: HouseholdReportSimulation,
        current_policyengine_version: str,
    ) -> None:
        """Read countries and catalog versions through ``database_session``.

        Stored households and policies are read through ``households`` and
        ``policies``, reports through ``simulation``.
        ``current_policyengine_version`` selects the catalog version new runs
        use.
        """
        self._database_session = database_session
        self._households = households
        self._policies = policies
        self._simulation = simulation
        self._current_policyengine_version = current_policyengine_version

    def _require_household_reports(self, country_id: str) -> None:
        with self._database_session.read() as session:
            country = read_country(session, country_id)
        require_household_reports_supported(country, country_id=country_id)

    def _with_policyengine_versions(
        self, reports: tuple[HouseholdReportRecord, ...]
    ) -> tuple[HouseholdReportRecord, ...]:
        catalog_version_ids = run_catalog_version_ids(reports)
        if not catalog_version_ids:
            return reports
        with self._database_session.read() as session:
            versions = read_policyengine_versions(session, catalog_version_ids)
        return tuple(with_policyengine_version(report, versions) for report in reports)

    def submit_report(
        self, *, country_id: str, report_input: HouseholdReportFields
    ) -> HouseholdReportRecord:
        """Create a household report and its first run in the entrypoint.

        Raise ``HouseholdReportsUnsupportedError`` for a country without
        household calculations, ``HouseholdNotFoundError`` or
        ``PolicyNotFoundError`` for a household or policy the country does not
        have, and ``HouseholdReportYearError`` for a household without a
        default year, all before the entrypoint is asked; and
        ``SimulationRequestRefusedError`` when the entrypoint refuses the
        household or a policy.
        """
        self._require_household_reports(country_id)
        household = self._households.get_household(
            country_id=country_id, household_id=report_input.household_id
        )
        for choice in (report_input.baseline, report_input.reform):
            if choice is not None and choice.policy_id is not None:
                self._policies.get_policy(
                    country_id=country_id, policy_id=choice.policy_id
                )
        require_default_year(household.default_year)
        report = self._simulation.submit_report(
            household_report_submission(
                report_input,
                country_id=country_id,
                policyengine_version=self._current_policyengine_version,
            )
        )
        (report,) = self._with_policyengine_versions((report,))
        return report
