"""Conversions between stored countries rows and service read records."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.countries.types import CountryRead

if TYPE_CHECKING:
    from policyengine_api.data.v2.models import Country


def country_read(country: Country) -> CountryRead:
    """Convert one stored countries row to the service's read record."""
    return CountryRead(
        id=country.id,
        household_enabled=country.household_enabled,
        society_wide_enabled=country.society_wide_enabled,
    )
