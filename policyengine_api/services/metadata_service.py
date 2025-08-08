from policyengine_api.country import COUNTRIES
from policyengine_api.structured_logger import get_logger, log_struct

logger = get_logger()


class MetadataService:
    def get_metadata(self, country_id: str) -> dict:

        # Log the metadata retrieval attempt
        log_struct(
            event="MetadataService.get_metadata_called",
            input_data={
                "country_id": country_id,
            },
            message="Metadata retrieval called.",
            severity="INFO",
        )

        try:
            country = COUNTRIES.get(country_id)
            if country == None:
                error_msg = f"Attempted to get metadata for a nonexistant country: '{country_id}'"
                log_struct(
                    event="MetadataService.get_metadata_failed",
                    input_data={
                        "country_id": country_id,
                        "error": error_msg,
                    },
                    message=f"Metadata successfully retrieved for country_id '{country_id}'",
                    severity="ERROR",
                )

                raise RuntimeError(error_msg)

            metadata = country.metadata

            log_struct(
                event="MetadataService.get_metadata_success",
                input_data={
                    "country_id": country_id,
                },
                message="Metadata successfully retrieved.",
                severity="INFO",
            )

            return metadata

        except Exception as e:
            log_struct(
                event="MetadataService.get_metadata_exception",
                input_data={
                    "country_id": country_id,
                    "error": str(e),
                },
                message="Exception occurred while retrieving metadata.",
                severity="ERROR",
            )

            raise RuntimeError(
                f"Unexpected error retrieving metadata for country_id '{country_id}': {e}"
            ) from e
