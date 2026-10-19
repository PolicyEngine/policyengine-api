"""Flask view decorator that rejects unsupported country IDs."""

from __future__ import annotations

from functools import wraps
from typing import TYPE_CHECKING, TypeVar

from policyengine_api.country_validation import (
    InvalidCountryError,
    ensure_supported_country,
)
from policyengine_api.response_factory import _make_error_response

if TYPE_CHECKING:
    from collections.abc import Callable

    from flask import Response

_ViewResult = TypeVar("_ViewResult")


def validate_country(
    func: Callable[..., _ViewResult],
) -> Callable[..., _ViewResult | Response]:
    """Wrap a Flask view so an unsupported ``country_id`` gets 400 before the view runs.

    The 400 body is the shared JSON error payload, sent with the legacy v1
    content type that native FastAPI routes must match.

    Args:
        func (Callable): The view to wrap; it takes ``country_id`` as its first
            argument.

    Returns:
        Callable: The wrapped view, which returns a 400 response for an
        unsupported country and the view's own result otherwise.

    """

    @wraps(func)
    def validate_country_wrapper(
        country_id: str, *args: object, **kwargs: object
    ) -> _ViewResult | Response:
        try:
            ensure_supported_country(country_id)
        except InvalidCountryError as error:
            # Preserve the legacy v1 content type while native FastAPI routes
            # are contractually required to match the Flask response.
            return _make_error_response(error, 400, mimetype=None)
        return func(country_id, *args, **kwargs)

    return validate_country_wrapper
