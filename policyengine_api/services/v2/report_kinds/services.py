"""Serve ``/v2/reports`` for both kinds of report: economy and household.

A submission names its kind. Each kind's service, and the entrypoint's
routes behind it, handle only reports of that kind, so a report read by its
ID is looked for among economy reports first and then among household
reports. A failure other than "not found", such as an unavailable
simulation service, is never taken for a missing report.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.economy_reports.validators import (
    EconomyReportNotFoundError,
    EconomyReportsUnsupportedError,
)
from policyengine_api.services.v2.household_reports.types import (
    HouseholdReportFields,
)
from policyengine_api.services.v2.household_reports.validators import (
    HouseholdReportNotFoundError,
)
from policyengine_api.services.v2.report_kinds.validators import report_not_found

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from uuid import UUID

    from policyengine_api.services.v2.economy_reports.types import EconomyReportFields
    from policyengine_api.services.v2.household_reports.types import (
        HouseholdReportRecord,
        HouseholdReportRunRecord,
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

    def get_report(
        self, *, country_id: str, report_id: UUID
    ) -> EconomyReportRecord | HouseholdReportRecord:
        """Return the country's report of either kind.

        An economy report with no run starts its first run, as
        ``V2EconomyReportService.get_report`` does. Raise
        ``ReportNotFoundError`` when the country has neither kind by this ID.
        """
        try:
            return self._economy_reports().get_report(
                country_id=country_id, report_id=report_id
            )
        except EconomyReportNotFoundError:
            pass
        try:
            return self._household_reports().get_report(
                country_id=country_id, report_id=report_id
            )
        except HouseholdReportNotFoundError as error:
            raise report_not_found(
                country_id=country_id, reference=str(report_id)
            ) from error

    def get_report_by_legacy_number(
        self, *, country_id: str, legacy_report_id: int
    ) -> EconomyReportRecord:
        """Return the economy report migrated from a v1 report output number."""
        return self._economy_reports().get_report_by_legacy_number(
            country_id=country_id, legacy_report_id=legacy_report_id
        )

    def run_report(
        self, *, country_id: str, report_id: UUID, force: bool
    ) -> EconomyReportRunRecord | HouseholdReportRunRecord:
        """Run the country's report of either kind again on the current version.

        A household-only country has no economy reports, so its report is
        looked for among household reports at once. When the country has
        neither kind by this ID, the economy refusal of a household-only
        country (``EconomyReportsUnsupportedError``) stands, and otherwise
        ``ReportNotFoundError`` is raised.
        """
        try:
            return self._economy_reports().run_report(
                country_id=country_id, report_id=report_id, force=force
            )
        except (EconomyReportNotFoundError, EconomyReportsUnsupportedError) as error:
            economy_refusal: Exception = error
        try:
            return self._household_reports().run_report(
                country_id=country_id, report_id=report_id, force=force
            )
        except HouseholdReportNotFoundError as error:
            if isinstance(economy_refusal, EconomyReportsUnsupportedError):
                raise economy_refusal from error
            raise report_not_found(
                country_id=country_id, reference=str(report_id)
            ) from error

    def list_reports(
        self, *, country_id: str, report_ids: Sequence[UUID]
    ) -> tuple[EconomyReportRecord | HouseholdReportRecord, ...]:
        """Return the country's reports of both kinds among ``report_ids``.

        They are in that order, once each. IDs that are not economy reports
        the simulation service has are looked for among the country's
        household reports; an economy report whose stored result cannot be
        read back is left out, as before, without that lookup.
        """
        requested = tuple(dict.fromkeys(report_ids))
        economy_listing = self._economy_reports().find_reports(
            country_id=country_id, report_ids=requested
        )
        found: dict[UUID, EconomyReportRecord | HouseholdReportRecord] = {
            report.id: report for report in economy_listing.reports
        }
        # An economy report whose result cannot be read back is not missing.
        not_missing = set(found) | set(economy_listing.unreadable_report_ids)
        remaining = [
            report_id for report_id in requested if report_id not in not_missing
        ]
        if remaining:
            found.update(
                (report.id, report)
                for report in self._household_reports().list_reports(
                    country_id=country_id, report_ids=remaining
                )
            )
        return tuple(found[report_id] for report_id in requested if report_id in found)

    def list_report_runs(
        self, *, country_id: str, report_id: UUID
    ) -> tuple[EconomyReportRunRecord, ...]:
        """Return an economy report's runs, newest first."""
        return self._economy_reports().list_report_runs(
            country_id=country_id, report_id=report_id
        )
