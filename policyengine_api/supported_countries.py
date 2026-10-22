"""The countries the Public API serves, listed once in code.

``SupportedCountryId`` is the one country list. Every other list derives from
it: the v2 routes' ``CountryId`` type, the countries catalog extraction
publishes, and the countries the v1 routes copy into v2 (dual-write). Adding
a country starts here.

The v2 ``countries`` table records what each country supports, and must hold
one row for each listed country and no other: a v2 Alembic revision inserts
the row when a country is added. The application refuses to start when they
differ (``policyengine_api.startup_country_check``).

The module imports nothing from the package, so modules that the query
models import, such as the catalog package, can import it too.
"""

from __future__ import annotations

from typing import Final, Literal, get_args

SupportedCountryId = Literal["us", "uk"]
SUPPORTED_COUNTRY_IDS: Final[tuple[SupportedCountryId, ...]] = get_args(
    SupportedCountryId
)
