"""Database-independent validation for ``/v2/reports`` across both kinds."""

from __future__ import annotations


class ReportNotFoundError(LookupError):
    """The country has neither an economy report nor a household report by this ID."""


def report_not_found(*, country_id: str, reference: str) -> ReportNotFoundError:
    """Build the error for a report of neither kind in the country."""
    return ReportNotFoundError(
        f"Report {reference} was not found in country {country_id!r}"
    )
