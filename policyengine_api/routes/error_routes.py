from flask import Blueprint, Response
from werkzeug.exceptions import (
    HTTPException,
)

from policyengine_api.response_factory import _make_error_response

error_bp = Blueprint("error", __name__)


@error_bp.app_errorhandler(404)
def response_404(error) -> Response:
    """Specific handler for 404 Not Found errors"""
    return _make_error_response(error, 404, result=None)


@error_bp.app_errorhandler(400)
def response_400(error) -> Response:
    """Specific handler for 400 Bad Request errors"""
    return _make_error_response(error, 400, result=None)


@error_bp.app_errorhandler(401)
def response_401(error) -> Response:
    """Specific handler for 401 Unauthorized errors"""
    return _make_error_response(error, 401, result=None)


@error_bp.app_errorhandler(403)
def response_403(error) -> Response:
    """Specific handler for 403 Forbidden errors"""
    return _make_error_response(error, 403, result=None)


@error_bp.app_errorhandler(500)
def response_500(error) -> Response:
    """Specific handler for 500 Internal Server errors"""
    return _make_error_response(error, 500, result=None)


@error_bp.app_errorhandler(HTTPException)
def response_http_exception(error: HTTPException) -> Response:
    """Generic handler for HTTPException; should be raised if no specific handler is found"""
    return _make_error_response(error, error.code, result=None)


@error_bp.app_errorhandler(Exception)
def response_generic_error(error: Exception) -> Response:
    """Handler for any unhandled exceptions"""
    return _make_error_response(error, 500, result=None)
