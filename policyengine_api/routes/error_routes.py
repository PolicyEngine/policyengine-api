import json
from flask import Response, Flask
from werkzeug.exceptions import (
    HTTPException,
    NotFound,
    BadRequest,
    Unauthorized,
    Forbidden,
    InternalServerError,
)


class ErrorRoutes:
    """
    Error routing class
    """

    @staticmethod
    def init_app(app: Flask) -> None:
        """
        Register all error handlers with the Flask app

        Args:
            app (Flask): The Flask app to register error handlers
        """
        app.register_error_handler(404, ErrorRoutes.handle_404)
        app.register_error_handler(400, ErrorRoutes.handle_400)
        app.register_error_handler(401, ErrorRoutes.handle_401)
        app.register_error_handler(403, ErrorRoutes.handle_403)
        app.register_error_handler(500, ErrorRoutes.handle_500)
        app.register_error_handler(
            HTTPException, ErrorRoutes.handle_http_exception
        )
        app.register_error_handler(Exception, ErrorRoutes.handle_generic_error)

    @staticmethod
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

    @staticmethod
    def handle_404(error: NotFound) -> Response:
        """Specific handler for 404 Not Found errors"""
        return Response(
            json.dumps(
                {
                    "status": "error",
                    "message": (
                        str(error)
                        if str(error)
                        else "The requested resource was not found"
                    ),
                    "result": None,
                }
            ),
            404,
            mimetype="application/json",
        )

    @staticmethod
    def handle_400(error: BadRequest) -> Response:
        """Specific handler for 400 Bad Request errors"""
        return Response(
            json.dumps(
                {
                    "status": "error",
                    "message": (
                        str(error)
                        if str(error)
                        else "The request was malformed"
                    ),
                    "result": None,
                }
            ),
            400,
            mimetype="application/json",
        )

    @staticmethod
    def handle_401(error: Unauthorized) -> Response:
        """Specific handler for 401 Unauthorized errors"""
        return Response(
            json.dumps(
                {
                    "status": "error",
                    "message": (
                        str(error)
                        if str(error)
                        else "Authentication is required"
                    ),
                    "result": None,
                }
            ),
            401,
            mimetype="application/json",
        )

    @staticmethod
    def handle_403(error: Forbidden) -> Response:
        """Specific handler for 403 Forbidden errors"""
        return Response(
            json.dumps(
                {
                    "status": "error",
                    "message": (
                        str(error)
                        if str(error)
                        else "You do not have permission to access this resource"
                    ),
                    "result": None,
                }
            ),
            403,
            mimetype="application/json",
        )

    @staticmethod
    def handle_500(error: InternalServerError) -> Response:
        """Specific handler for 500 Internal Server Error"""
        return Response(
            json.dumps(
                {
                    "status": "error",
                    "message": (
                        str(error)
                        if str(error)
                        else "An internal server error occurred"
                    ),
                    "result": None,
                }
            ),
            500,
            mimetype="application/json",
        )

    @staticmethod
    def handle_generic_error(error: Exception) -> Response:
        """Handler for any unhandled exceptions"""
        return Response(
            json.dumps(
                {
                    "status": "error",
                    "message": (
                        str(error)
                        if str(error)
                        else "An unexpected error occurred"
                    ),
                    "result": None,
                }
            ),
            500,
            mimetype="application/json",
        )
