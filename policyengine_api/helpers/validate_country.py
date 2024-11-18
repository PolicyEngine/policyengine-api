from typing import Union
from flask import Response
import json
from policyengine_api.constants import COUNTRIES


def validate_country(country_id: str) -> Union[None, Response]:
    """Validate that a country ID is valid. If not, return a 404 response.

    Args:
        country_id (str): The country ID to validate.

    Returns:

    """
    if country_id not in COUNTRIES:
        body = dict(
            status="error",
            message=f"Country {country_id} not found. Available countries are: {', '.join(COUNTRIES)}",
        )
        return Response(json.dumps(body), status=404)
    return None
