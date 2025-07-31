from policyengine_api.country import COUNTRIES
from policyengine_api.gcp_logging import logger


class MetadataService:
    def get_metadata(self, country_id: str) -> dict:

        # Log the metadata retrieval attempt
        logger.log_struct(
            {
                "event": "MetadataService.get_metadata_called",
                "country_id": country_id,
            },
            severity="INFO",
        )

        try:
            country = COUNTRIES.get(country_id)
            if country is None:
                error_msg = f"Attempted to get metadata for a nonexistant country: '{country_id}'"
                logger.log_struct(
                    {
                        "event": "MetadataService.get_metadata_failed",
                        "country_id": country_id,
                        "message": f"Metadata successfully retrieved for country_id '{country_id}'",
                        "error": error_msg,
                    },
                    severity="ERROR",
                )
                raise RuntimeError(error_msg)

            metadata = country.metadata

            logger.log_struct(
                {
                    "event": "MetadataService.get_metadata_success",
                    "country_id": country_id,
                },
                severity="INFO",
            )

            return metadata

        except Exception as e:
            logger.log_struct(
                {
                    "event": "MetadataService.get_metadata_exception",
                    "country_id": country_id,
                    "error": str(e),
                },
                severity="ERROR",
            )
            raise RuntimeError(
                f"Unexpected error retrieving metadata for country_id '{country_id}': {e}"
            ) from e
