"""Serve ``/v2/reports`` for both kinds of report: economy and household.

A submission names its kind. Each kind's service, and the entrypoint's
routes behind it, handle only reports of that kind.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.household_reports.types import (
    HouseholdReportFields,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from uuid import UUID

    from policyengine_api.services.v2.economy_reports.types import EconomyReportFields
    from policyengine_api.services.v2.household_reports.types import (
        HouseholdReportRecord,
    )
    from policyengine_api.services.v2.report_kinds.types import (
        EconomyReportOperations,
        HouseholdReportOperations,
    )
    from policyengine_api.services.v2.simulation_entrypoint.types import (
        EconomyReportRecord,
        EconomyReportRunRecord,
    )


class V2ReportService:
    """Send each ``/v2/reports`` operation to the economy or household service.

    Each service is built from its factory the first time it is needed.
    """

    def __init__(
        self,
        *,
        economy_reports: Callable[[], EconomyReportOperations],
        household_reports: Callable[[], HouseholdReportOperations],
    ) -> None:
        """Build each kind's service with its factory, at its first use."""
        self._economy_factory = economy_reports
        self._household_factory = household_reports
        self._economy: EconomyReportOperations | None = None
        self._household: HouseholdReportOperations | None = None

    def _economy_reports(self) -> EconomyReportOperations:
        if self._economy is None:
            self._economy = self._economy_factory()
        return self._economy

    def _household_reports(self) -> HouseholdReportOperations:
        if self._household is None:
            self._household = self._household_factory()
        return self._household

    def submit_report(
        self,
        *,
        country_id: str,
        report_input: EconomyReportFields | HouseholdReportFields,
    ) -> EconomyReportRecord | HouseholdReportRecord:
        """Create a report of the submission's kind and start its first run."""
        if isinstance(report_input, HouseholdReportFields):
            return self._household_reports().submit_report(
                country_id=country_id, report_input=report_input
            )
        return self._economy_reports().submit_report(
            country_id=country_id, report_input=report_input
        )

    def get_report(self, *, country_id: str, report_id: UUID) -> EconomyReportRecord:
        """Return an economy report of the country."""
        return self._economy_reports().get_report(
            country_id=country_id, report_id=report_id
        )

    def get_report_by_legacy_number(
        self, *, country_id: str, legacy_report_id: int
    ) -> EconomyReportRecord:
        """Return the economy report migrated from a v1 report output number."""
        return self._economy_reports().get_report_by_legacy_number(
            country_id=country_id, legacy_report_id=legacy_report_id
        )

    def run_report(
        self, *, country_id: str, report_id: UUID, force: bool
    ) -> EconomyReportRunRecord:
        """Run an economy report again on the current catalog version."""
        return self._economy_reports().run_report(
            country_id=country_id, report_id=report_id, force=force
        )

    def list_reports(
        self, *, country_id: str, report_ids: Sequence[UUID]
    ) -> tuple[EconomyReportRecord, ...]:
        """Return the country's economy reports among ``report_ids``."""
        return self._economy_reports().list_reports(
            country_id=country_id, report_ids=report_ids
        )

    def list_report_runs(
        self, *, country_id: str, report_id: UUID
    ) -> tuple[EconomyReportRunRecord, ...]:
        """Return an economy report's runs, newest first."""
        return self._economy_reports().list_report_runs(
            country_id=country_id, report_id=report_id
        )
