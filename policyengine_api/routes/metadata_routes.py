import json
from flask import Blueprint, Response

from policyengine_api.utils.payload_validators import validate_country
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
    metadata = metadata_service.get_metadata(country_id)

    return Response(
        json.dumps(
            {
                "status": "ok",
                "message": None,
                "result": metadata,
            }
        ),
        status=200,
        mimetype="application/json",
    )
