from policyengine_api.country import COUNTRIES
from flask import Response, json, request
from policyengine_api.structured_logger import get_logger, log_struct
import uuid

logger = get_logger()


class MetadataService:
    def get_metadata(self, country_id: str) -> dict:

        # Generate a unique request ID for tracing
        request_id = uuid.uuid4().hex

        # Common log context
        log_context = {
            "request_id": request_id,
            "endpoint": "MetadataService.get_metadata",
            "country_id": country_id,
            "request_path": request.path,
        }

        # Log the metadata retrieval attempt
        log_struct(
            event="metadata_retrieval_called",
            input_data=log_context,
            message="Metadata retrieval called.",
            severity="INFO",
        )

        try:
            country = COUNTRIES.get(country_id)
            if country == None:
                error_msg = f"Attempted to get metadata for a nonexistant country: '{country_id}'"
                log_struct(
                    event="metadata_retrieval_failed",
                    input_data=log_context,
                    message=error_msg,
                    severity="WARNING",
                )

                # Return structured 404 response
                response_body = dict(status="error", message=error_msg)
                return Response(
                    json.dumps(response_body),
                    status=404,
                    mimetype="application/json",
                )

            # Retrieve metadata from the country object
            metadata = country.metadata

            # Success log
            log_struct(
                event="metadata_retrieval_success",
                input_data=log_context,
                message="Metadata successfully retrieved.",
                severity="INFO",
            )

            return Response(
                json.dumps(
                    {"status": "ok", "message": None, "result": metadata}
                ),
                status=200,
                mimetype="application/json",
            )

        except Exception as e:
            log_struct(
                event="metadata_retrieval_exception",
                input_data=log_context,
                message="Exception occurred while retrieving metadata.",
                severity="ERROR",
            )

            response_body = dict(
                status="error",
                message=f"Unexpected error encountered while retrieving metadata for country_id '{country_id}': {e}",
            )
            return Response(
                json.dumps(response_body),
                status=500,
                mimetype="application/json",
            )
