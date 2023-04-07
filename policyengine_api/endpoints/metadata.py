from policyengine_api.country import COUNTRIES, validate_country


def get_metadata(country_id: str) -> dict:
    """Get metadata for a country.

    Args:
        country_id (str): The country ID.
    """
    invalid_country = validate_country(country_id)
    if invalid_country:
        return invalid_country

    return COUNTRIES.get(country_id).metadata
