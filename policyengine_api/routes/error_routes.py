import json
from flask import Response, Blueprint
from werkzeug.exceptions import (
    HTTPException,
)

error_bp = Blueprint("error", __name__)


@error_bp.app_errorhandler(404)
def handle_404(error) -> Response:
    """Specific handler for 404 Not Found errors"""
    return make_error_response(error, 404)


@error_bp.app_errorhandler(400)
def handle_400(error) -> Response:
    """Specific handler for 400 Bad Request errors"""
    return make_error_response(error, 400)


@error_bp.app_errorhandler(401)
def handle_401(error) -> Response:
    """Specific handler for 401 Unauthorized errors"""
    return make_error_response(error, 401)


@error_bp.app_errorhandler(403)
def handle_403(error) -> Response:
    """Specific handler for 403 Forbidden errors"""
    return make_error_response(error, 403)


@error_bp.app_errorhandler(500)
def handle_500(error) -> Response:
    """Specific handler for 500 Internal Server errors"""
    return make_error_response(error, 500)


@error_bp.app_errorhandler(HTTPException)
def handle_http_exception(error: HTTPException) -> Response:
    """Generic handler for HTTPException; should be raised if no specific handler is found"""
    return make_error_response(str(error), error.code)


@error_bp.app_errorhandler(Exception)
def handle_generic_error(error: Exception) -> Response:
    """Handler for any unhandled exceptions"""
    return make_error_response(str(error), 500)


def make_error_response(
    error,
    status_code: int,
) -> Response:
    """Create a generic error response"""
    return Response(
        json.dumps(
            {
                "status": "error",
                "message": str(error),
                "result": None,
            }
        ),
        status_code,
        mimetype="application/json",
    )
