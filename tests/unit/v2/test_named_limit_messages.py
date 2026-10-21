"""Pin the checks and messages behind the limits named in the complexity refactor."""

from __future__ import annotations

import pytest

from policyengine_api.data.places import validate_place_code
from policyengine_api.data.v2.catalog.catalog_selection import (
    InvalidPolicyEngineVersionError,
    validate_policyengine_version,
)
from policyengine_api.services.v2.metadata.validators import (
    InvalidMetadataPageError,
    validate_metadata_page,
)
from policyengine_api.services.v2.policies.transformations import (
    parse_legacy_period,
)
from policyengine_api.services.v2.policies.validators import (
    LegacyPolicyTranslationError,
)


def test_policyengine_version_is_bounded_to_128_characters() -> None:
    longest = "1." + "1" * 126
    assert len(longest) == 128

    assert validate_policyengine_version(longest) == longest
    with pytest.raises(
        InvalidPolicyEngineVersionError,
        match=r"^policyengine_version must be at most 128 characters$",
    ):
        validate_policyengine_version(longest + "0")


@pytest.mark.parametrize("period", ["2026-01-01.2026-06-30.2026-12-31", "a.b.c"])
def test_legacy_period_with_more_than_one_date_range_is_rejected(period: str) -> None:
    with pytest.raises(
        LegacyPolicyTranslationError,
        match=rf"^legacy period '{period}' must contain one date range$",
    ):
        parse_legacy_period(period)


@pytest.mark.parametrize(
    ("offset", "limit", "message"),
    [
        (-1, 1, "offset must be at least 0"),
        (0, 0, "limit must be between 1 and 500"),
        (0, 501, "limit must be between 1 and 500"),
    ],
)
def test_metadata_pages_are_bounded(offset: int, limit: int, message: str) -> None:
    assert validate_metadata_page(0, 500) == (0, 500)
    with pytest.raises(InvalidMetadataPageError, match=rf"^{message}$"):
        validate_metadata_page(offset, limit)


@pytest.mark.parametrize("place_fips", ["5700", "570000", "5700A"])
def test_place_codes_need_a_five_digit_fips_code(place_fips: str) -> None:
    validate_place_code("NJ-57000")
    with pytest.raises(
        ValueError,
        match=(
            rf"^Invalid FIPS code in place: '{place_fips}'\. "
            "Expected 5-digit FIPS code$"
        ),
    ):
        validate_place_code(f"NJ-{place_fips}")
