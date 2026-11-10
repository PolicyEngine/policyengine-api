"""Checks of a household calculation against values already loaded."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from policyengine_api.services.v2.countries.types import CountryRead


class HouseholdCalculationCountryError(ValueError):
    """The country does not offer household calculations."""


class HouseholdCalculationYearError(ValueError):
    """The household has no default year to calculate."""


def require_household_country(
    countries: Iterable[CountryRead], country_id: str
) -> None:
    """Raise HouseholdCalculationCountryError unless the country calculates households.

    A household-only country (household calculations without society-wide
    reports) passes; a country without a ``countries`` row does not.
    """
    for country in countries:
        if country.id == country_id and country.household_enabled:
            return
    msg = f"Household calculations are not available for country {country_id}."
    raise HouseholdCalculationCountryError(msg)


def require_default_year(default_year: int | None) -> None:
    """Raise HouseholdCalculationYearError unless the household has a default year.

    The simulation service calculates that year, the year the household's
    values name.
    """
    if default_year is None:
        msg = "This household has no default year to calculate."
        raise HouseholdCalculationYearError(msg)
