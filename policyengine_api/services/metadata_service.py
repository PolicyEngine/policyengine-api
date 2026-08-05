from policyengine_api.country import COUNTRIES
from policyengine_api.json_types import JSONObject


class MetadataService:
    def get_metadata(self, country_id: str) -> JSONObject:
        country = COUNTRIES.get(country_id)
        if country is None:
            raise RuntimeError(
                f"Attempted to get metadata for a nonexistant country: '{country_id}'"
            )

        return country.metadata
