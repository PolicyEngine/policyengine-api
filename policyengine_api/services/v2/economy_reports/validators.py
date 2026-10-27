"""Database-independent validation for v2 economy report operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from policyengine_api.data.v2.models import Country


class EconomyReportsUnsupportedError(ValueError):
    """The country does not have economy (society-wide) reports.

    Its countries row leaves ``society_wide_enabled`` unset, as for a
    household-only country, or it has no row.
    """


def require_economy_reports_supported(
    country: Country | None, *, country_id: str
) -> None:
    """Raise ``EconomyReportsUnsupportedError`` unless the row allows them."""
    if country is None or not country.society_wide_enabled:
        msg = f"Economy reports are not available for country {country_id!r}"
        raise EconomyReportsUnsupportedError(msg)
