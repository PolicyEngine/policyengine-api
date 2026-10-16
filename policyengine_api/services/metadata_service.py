"""Read access to the metadata document of each loaded country model."""

from policyengine_api.country import COUNTRIES
from policyengine_api.json_types import JSONObject


class MetadataService:
    """Service that returns a country's metadata from the loaded country models."""

    def get_metadata(self, country_id: str) -> JSONObject:
        """Return the country's metadata; raise RuntimeError for an unknown country."""
        country = COUNTRIES.get(country_id)
        if country is None:
            msg = f"Attempted to get metadata for a nonexistant country: '{country_id}'"
            raise RuntimeError(msg)

        return country.metadata
