"""App-wide Flask error handlers that return the shared JSON error envelope."""

from flask import Blueprint, Response
from werkzeug.exceptions import (
    HTTPException,
)

from policyengine_api.response_factory import _make_error_response

error_bp = Blueprint("error", __name__)


@error_bp.app_errorhandler(404)
def response_404(error: HTTPException) -> Response:
    """Return 404 Not Found as a JSON error body."""
    return _make_error_response(error, 404, result=None)


@error_bp.app_errorhandler(400)
def response_400(error: HTTPException) -> Response:
    """Return 400 Bad Request as a JSON error body."""
    return _make_error_response(error, 400, result=None)


@error_bp.app_errorhandler(401)
def response_401(error: HTTPException) -> Response:
    """Return 401 Unauthorized as a JSON error body."""
    return _make_error_response(error, 401, result=None)


@error_bp.app_errorhandler(403)
def response_403(error: HTTPException) -> Response:
    """Return 403 Forbidden as a JSON error body."""
    return _make_error_response(error, 403, result=None)


@error_bp.app_errorhandler(500)
def response_500(error: HTTPException) -> Response:
    """Return 500 Internal Server Error as a JSON error body."""
    return _make_error_response(error, 500, result=None)


@error_bp.app_errorhandler(HTTPException)
def response_http_exception(error: HTTPException) -> Response:
    """Return any other HTTPException as a JSON error body with its own status."""
    return _make_error_response(error, error.code, result=None)


@error_bp.app_errorhandler(Exception)
def response_generic_error(error: Exception) -> Response:
    """Return an unhandled exception as a 500 JSON error body carrying its message."""
    return _make_error_response(error, 500, result=None)
