"""Database-independent validation for v2 economy report operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from policyengine_api.data.v2.models import Country
    from policyengine_api.services.v2.economy_reports.types import (
        EconomyReportRecord,
    )


class EconomyReportsUnsupportedError(ValueError):
    """The country does not have economy (society-wide) reports.

    Its countries row leaves ``society_wide_enabled`` unset, as for a
    household-only country, or it has no row.
    """


class EconomyReportNotFoundError(LookupError):
    """The simulation service has no such report in the requested country."""


def economy_reports_supported(country: Country | None) -> bool:
    """Return whether a countries row allows economy (society-wide) reports."""
    return country is not None and country.society_wide_enabled


def require_economy_reports_supported(
    country: Country | None, *, country_id: str
) -> None:
    """Raise ``EconomyReportsUnsupportedError`` unless the row allows them."""
    if not economy_reports_supported(country):
        msg = f"Economy reports are not available for country {country_id!r}"
        raise EconomyReportsUnsupportedError(msg)


def require_report_in_country(
    report: EconomyReportRecord | None, *, country_id: str, reference: str
) -> EconomyReportRecord:
    """Return the report, or raise ``EconomyReportNotFoundError``.

    A report of another country is not found, as it would be in a country's
    own list. ``reference`` names the requested report in the message.
    """
    if report is None or report.country_id != country_id:
        msg = f"Economy report {reference} was not found in country {country_id!r}"
        raise EconomyReportNotFoundError(msg)
    return report
