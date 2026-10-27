"""Checks of a household calculation against what is already loaded."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from policyengine_api.services.v2.countries.types import CountryRead


class HouseholdCalculationCountryError(ValueError):
    """The country does not offer household calculations."""


class HouseholdCalculationYearError(ValueError):
    """The household has no default year to calculate."""


class HouseholdCalculationNotFoundError(LookupError):
    """The simulation service has no such household calculation."""


def require_household_country(
    countries: Iterable[CountryRead], country_id: str
) -> None:
    """Raise HouseholdCalculationCountryError unless the country calculates households.

    A household-only country (household calculations without society-wide
    reports) passes.
    """
    for country in countries:
        if country.id == country_id and country.household_enabled:
            return
    msg = f"Household calculations are not available for country {country_id}."
    raise HouseholdCalculationCountryError(msg)


def calculation_year(default_year: int | None) -> int:
    """Return the household's default year, the year its values name."""
    if default_year is None:
        msg = "This household has no default year to calculate."
        raise HouseholdCalculationYearError(msg)
    return default_year
