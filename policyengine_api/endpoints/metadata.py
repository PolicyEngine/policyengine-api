from policyengine_api.utils.payload_validators import validate_country
from policyengine_api.country import COUNTRIES


@validate_country
def get_metadata(country_id: str) -> dict:
    """Get metadata for a country.

    Args:
        country_id (str): The country ID.
    """
    return COUNTRIES.get(country_id).metadata
