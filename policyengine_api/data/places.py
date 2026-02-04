"""
US Census place code parsing and validation utilities.

Place codes follow the format: STATE_ABBREV-PLACE_FIPS
Example: NJ-57000 for Newark, NJ
"""

from policyengine_api.data.congressional_districts import get_valid_state_codes


def parse_place_code(place_code: str) -> tuple[str, str]:
    """
    Parse a place code into its state abbreviation and FIPS components.

    Args:
        place_code: Place code in format STATE_ABBREV-PLACE_FIPS (e.g., "NJ-57000")

    Returns:
        Tuple of (state_abbrev, place_fips)

    Raises:
        ValueError: If the place code format is invalid
    """
    if "-" not in place_code:
        raise ValueError(
            f"Invalid place format: '{place_code}'. "
            "Expected format: STATE_ABBREV-PLACE_FIPS (e.g., NJ-57000)"
        )
    return place_code.split("-", 1)


def validate_place_code(place_code: str) -> None:
    """
    Validate a place code has valid state abbreviation and FIPS format.

    Args:
        place_code: Place code in format STATE_ABBREV-PLACE_FIPS (e.g., "NJ-57000")

    Raises:
        ValueError: If the state abbreviation or FIPS code is invalid
    """
    state_abbrev, place_fips = parse_place_code(place_code)

    if state_abbrev.lower() not in get_valid_state_codes():
        raise ValueError(f"Invalid state in place code: '{state_abbrev}'")

    if not place_fips.isdigit() or len(place_fips) != 5:
        raise ValueError(
            f"Invalid FIPS code in place: '{place_fips}'. "
            "Expected 5-digit FIPS code"
        )
