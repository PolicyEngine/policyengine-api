"""Lookup of each country's built-in current-law policy ID."""


def get_current_law_policy_id(country_id: str) -> int:
    """Return the ID of the stored policy that represents current law in a country.

    Raises KeyError for any other country.
    """
    return {
        "uk": 1,
        "us": 2,
    }[country_id]
