"""Database-independent checks of what is sent to the simulation service."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from policyengine_api.services.v2.countries.types import CountryRead


class EconomyCalculationsUnsupportedError(ValueError):
    """The country has no economy (society-wide) simulations or reports.

    Its countries row leaves ``society_wide_enabled`` unset, as for a
    household-only country, or it has no row.
    """


class SubmissionStorageError(RuntimeError):
    """A submission's countries, policies or catalog could not be read."""


def require_economy_country(countries: Iterable[CountryRead], country_id: str) -> None:
    """Raise EconomyCalculationsUnsupportedError unless the row allows economy runs."""
    for country in countries:
        if country.id == country_id and country.society_wide_enabled:
            return
    msg = f"Economy calculations are not available for country {country_id!r}"
    raise EconomyCalculationsUnsupportedError(msg)
