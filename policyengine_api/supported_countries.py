"""The countries the Public API serves, listed once in code.

``SupportedCountryId`` is the one country list. Every other list derives from
it: the v2 routes' ``CountryId`` type, the countries catalog extraction
publishes, and the countries the v1 routes copy into v2 (dual-write). Adding
a country starts here.

The module imports nothing from the package, so modules that the query
models import, such as the catalog package, can import it too.
"""

from __future__ import annotations

from typing import Final, Literal, get_args

SupportedCountryId = Literal["us", "uk"]
SUPPORTED_COUNTRY_IDS: Final[tuple[SupportedCountryId, ...]] = get_args(
    SupportedCountryId
)
