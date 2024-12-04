from functools import wraps
from typing import Union
from flask import Response
import json
from policyengine_api.constants import COUNTRIES


def validate_country(func):
    """Validate that a country ID is valid. If not, return a 400 response.

    Args:
        country_id (str): The country ID to validate.

    Returns:
        Response(400) if country is not valid, else continues
    """

    @wraps(func)
    def validate_country_wrapper(
        country_id: str, *args, **kwargs
    ) -> Union[None, Response]:
        print("Validating country")
        if country_id not in COUNTRIES:
            body = dict(
                status="error",
                message=f"Country {country_id} not found. Available countries are: {', '.join(COUNTRIES)}",
            )
            return Response(json.dumps(body), status=400)
        return func(country_id, *args, **kwargs)

    return validate_country_wrapper
