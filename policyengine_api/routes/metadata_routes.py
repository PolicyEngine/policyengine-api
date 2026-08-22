import json
from flask import Blueprint, Response

from policyengine_api.utils.payload_validators import validate_country
from policyengine_api.utils.streaming_json import (
    iter_body_chunks,
    should_stream_body,
)
from policyengine_api.services.metadata_service import MetadataService

metadata_bp = Blueprint("metadata", __name__)
metadata_service = MetadataService()


@metadata_bp.route("/<country_id>/metadata", methods=["GET"])
@validate_country
def get_metadata(country_id: str) -> Response:
    """Get metadata for a country.

    Args:
        country_id (str): The country ID.
    """

    # Retrieve country metadata and add status and message to the response
    country_metadata = metadata_service.get_metadata(country_id)
    body = json.dumps(
        {"status": "ok", "message": None, "result": country_metadata}
    ).encode("utf-8")
    if should_stream_body(body):
        return Response(
            iter_body_chunks(body),
            status=200,
            mimetype="application/json",
            direct_passthrough=True,
        )
    return Response(
        body,
        status=200,
        mimetype="application/json",
    )
