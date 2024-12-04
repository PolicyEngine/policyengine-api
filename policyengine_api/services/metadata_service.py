from policyengine_api.country import COUNTRIES


class MetadataService:
    def get_metadata(self, country_id: str) -> dict:
        country = COUNTRIES.get(country_id)
        if country == None:
            raise RuntimeError(
                f"Attempted to get metadata for a nonexistant country: '{country_id}'"
            )

        return country.metadata
