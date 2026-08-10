from functools import wraps
from typing import Union

from flask import Response

from policyengine_api.country_validation import (
    InvalidCountryError,
    ensure_supported_country,
)
from policyengine_api.response_factory import _make_error_response


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
        try:
            ensure_supported_country(country_id)
        except InvalidCountryError as error:
            # Preserve the legacy v1 content type while native FastAPI routes
            # are contractually required to match the Flask response.
            return _make_error_response(error, 400, mimetype=None)
        return func(country_id, *args, **kwargs)

    return validate_country_wrapper
