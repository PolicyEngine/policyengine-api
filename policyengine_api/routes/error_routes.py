import json
from flask import Response, Blueprint
from werkzeug.exceptions import (
    HTTPException,
    NotFound,
)

error_bp = Blueprint("error", __name__)


@error_bp.app_errorhandler(404)
def handle_404(error) -> Response:
    """Specific handler for 404 Not Found errors"""
    return Response(
        json.dumps(
            {
                "status": "error",
                "message": str(error),
                "result": None,
            }
        ),
        404,
        mimetype="application/json",
    )


@error_bp.app_errorhandler(400)
def handle_400(error) -> Response:
    """Specific handler for 400 Bad Request errors"""
    return Response(
        json.dumps(
            {
                "status": "error",
                "message": str(error),
                "result": None,
            }
        ),
        400,
        mimetype="application/json",
    )


@error_bp.app_errorhandler(401)
def handle_401(error) -> Response:
    """Specific handler for 401 Unauthorized errors"""
    return Response(
        json.dumps(
            {
                "status": "error",
                "message": str(error),
                "result": None,
            }
        ),
        401,
        mimetype="application/json",
    )


@error_bp.app_errorhandler(403)
def handle_403(error) -> Response:
    """Specific handler for 403 Forbidden errors"""
    return Response(
        json.dumps(
            {
                "status": "error",
                "message": str(error),
                "result": None,
            }
        ),
        403,
        mimetype="application/json",
    )


@error_bp.app_errorhandler(500)
def handle_500(error) -> Response:
    """Specific handler for 500 Internal Server Error"""
    return Response(
        json.dumps(
            {
                "status": "error",
                "message": str(error),
                "result": None,
            }
        ),
        500,
        mimetype="application/json",
    )


@error_bp.app_errorhandler(HTTPException)
def handle_http_exception(error: HTTPException) -> Response:
    """Generic handler for HTTPException; should be raised if no specific handler is found"""
    return Response(
        json.dumps(
            {
                "status": "error",
                "message": error.description,
                "result": None,
            }
        ),
        error.code,
        mimetype="application/json",
    )


@error_bp.app_errorhandler(Exception)
def handle_generic_error(error: Exception) -> Response:
    """Handler for any unhandled exceptions"""
    return Response(
        json.dumps(
            {
                "status": "error",
                "message": str(error),
                "result": None,
            }
        ),
        500,
        mimetype="application/json",
    )
