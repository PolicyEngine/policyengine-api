"""The economy and household report operations that ``/v2/reports`` serves."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from policyengine_api.services.v2.economy_reports.types import (
        EconomyReportFields,
        EconomyReportListing,
    )
    from policyengine_api.services.v2.household_reports.types import (
        HouseholdReportFields,
        HouseholdReportRecord,
        HouseholdReportRunRecord,
    )
    from policyengine_api.services.v2.simulation_entrypoint.types import (
        EconomyReportRecord,
        EconomyReportRunRecord,
    )


class EconomyReportOperations(Protocol):
    """Economy report operations (``V2EconomyReportService``)."""

    def submit_report(
        self, *, country_id: str, report_input: EconomyReportFields
    ) -> EconomyReportRecord:
        """Create a report and its first run on the current catalog version."""
        ...

    def get_report(self, *, country_id: str, report_id: UUID) -> EconomyReportRecord:
        """Return a report of the country, starting its first run if it has none."""
        ...

    def get_report_by_legacy_number(
        self, *, country_id: str, legacy_report_id: int
    ) -> EconomyReportRecord:
        """Return the report migrated from a v1 report output number."""
        ...

    def run_report(
        self, *, country_id: str, report_id: UUID, force: bool
    ) -> EconomyReportRunRecord:
        """Run a report again on the current catalog version."""
        ...

    def find_reports(
        self, *, country_id: str, report_ids: Sequence[UUID]
    ) -> EconomyReportListing:
        """List the country's reports among ``report_ids``, naming the unreadable."""
        ...

    def list_report_runs(
        self, *, country_id: str, report_id: UUID
    ) -> tuple[EconomyReportRunRecord, ...]:
        """Return a report's runs, newest first."""
        ...


class HouseholdReportOperations(Protocol):
    """Household report operations (``V2HouseholdReportService``)."""

    def submit_report(
        self, *, country_id: str, report_input: HouseholdReportFields
    ) -> HouseholdReportRecord:
        """Create a household report and its first run on the current version.

        Raise ``HouseholdReportsUnsupportedError`` for a country without
        household calculations, ``HouseholdNotFoundError`` or
        ``PolicyNotFoundError`` for a household or policy the country lacks,
        ``HouseholdReportYearError`` for a household without a default year,
        and ``SimulationRequestRefusedError`` when the entrypoint refuses it.
        """
        ...

    def get_report(self, *, country_id: str, report_id: UUID) -> HouseholdReportRecord:
        """Return a household report of the country with its newest run.

        Raise ``HouseholdReportNotFoundError`` when the country has no such one.
        """
        ...

    def list_reports(
        self, *, country_id: str, report_ids: Sequence[UUID]
    ) -> tuple[HouseholdReportRecord, ...]:
        """Return the country's household reports among ``report_ids``."""
        ...

    def run_report(
        self, *, country_id: str, report_id: UUID, force: bool
    ) -> HouseholdReportRunRecord:
        """Run a household report again on the current version (trigger ``manual``).

        Raise ``HouseholdReportNotFoundError`` for a report the country lacks
        and ``HouseholdReportsUnsupportedError`` for a country without
        household calculations.
        """
        ...
