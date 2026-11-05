"""The years offered for society-wide (economy) calculations, once per country.

``/{country}/metadata`` offers them in ``economy_options.time_period``, and
catalog extraction stores them as each v2 catalog version's
``metadata_time_periods``. The economy routes answer a society-wide request
for any other year with 400 and the code ``DATASET_YEAR_UNAVAILABLE``, even
when a result for that year is stored. Household calculations accept other
years.

Each list keeps the order both responses have always used: the US newest
first, the UK oldest first.

- The US years start in 2024: 2022 and 2023 are no longer offered.
- The UK years start with the data year of the UK dataset
  (microcosm_uk_2024_25), before which the simulation service refuses a UK
  year, and end with 2032, the last year policyengine-uk 2.151.0 projects
  that dataset to (``PROJECTION_END_YEAR``), after which it refuses one too.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

US_ECONOMY_YEARS: Final[tuple[int, ...]] = tuple(range(2035, 2023, -1))
UK_ECONOMY_YEARS: Final[tuple[int, ...]] = tuple(range(2024, 2033))

ECONOMY_YEARS: Final[Mapping[str, tuple[int, ...]]] = {
    "us": US_ECONOMY_YEARS,
    "uk": UK_ECONOMY_YEARS,
}

# The simulation service's code for a year its model and data do not cover,
# which the Public API also gives a society-wide request for a year outside
# ECONOMY_YEARS.
DATASET_YEAR_UNAVAILABLE: Final = "DATASET_YEAR_UNAVAILABLE"


def dataset_year_unavailable_message(country_id: str, year: str) -> str:
    """Return the message of the 400 for a society-wide request for ``year``.

    It names the country's first and last years and the requested year, in
    the words the simulation service uses for ``DATASET_YEAR_UNAVAILABLE``.
    """
    years = ECONOMY_YEARS[country_id]
    country = country_id.upper()
    return (
        f"{country} results are available for {min(years)} to {max(years)}. "
        f"{year} is outside the years the current {country} model and data cover."
    )
