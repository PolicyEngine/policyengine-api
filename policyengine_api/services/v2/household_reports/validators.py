"""Database-independent validation for v2 household report operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from policyengine_api.data.v2.models import Country
    from policyengine_api.services.v2.household_reports.types import (
        HouseholdReportRecord,
    )


class HouseholdReportsUnsupportedError(ValueError):
    """The country does not have household calculations.

    Its countries row leaves ``household_enabled`` unset, or it has no row. A
    household-only country has them.
    """


class HouseholdReportYearError(ValueError):
    """The stored household has no default year, the year a report calculates."""


class HouseholdReportNotFoundError(LookupError):
    """The simulation service has no such household report in the country."""


def require_household_reports_supported(
    country: Country | None, *, country_id: str
) -> None:
    """Raise ``HouseholdReportsUnsupportedError`` unless the row allows them."""
    if country is None or not country.household_enabled:
        msg = f"Household reports are not available for country {country_id!r}"
        raise HouseholdReportsUnsupportedError(msg)


def require_default_year(default_year: int | None) -> int:
    """Return the household's default year, or raise ``HouseholdReportYearError``."""
    if default_year is None:
        msg = "This household has no default year to calculate."
        raise HouseholdReportYearError(msg)
    return default_year


def require_report_in_country(
    report: HouseholdReportRecord | None, *, country_id: str, report_id: object
) -> HouseholdReportRecord:
    """Return the report, or raise ``HouseholdReportNotFoundError``.

    A report of another country is not found, as for economy reports.
    """
    if report is None or report.country_id != country_id:
        msg = f"Household report {report_id} was not found in country {country_id!r}"
        raise HouseholdReportNotFoundError(msg)
    return report
