import pytest
from flask import Flask
from werkzeug.exceptions import (
    BadRequest,
    Forbidden,
    InternalServerError,
    NotFound,
    Unauthorized,
)

from policyengine_api.routes.error_routes import error_bp


@pytest.fixture
def app():
    """Create and configure a new app instance for each test."""
    app = Flask(__name__)
    app.register_blueprint(error_bp)
    return app


@pytest.fixture
def client(app):
    """Create a test client for the app."""
    return app.test_client()


def test_404_handler(app, client):
    """Map NotFound to a 404 error envelope that keeps its message."""

    @app.route("/nonexistent")
    def nonexistent():
        msg = "Custom not found message"
        raise NotFound(msg)

    response = client.get("/nonexistent")
    data = response.get_json()

    assert response.status_code == 404
    assert data["status"] == "error"
    assert "Custom not found message" in data["message"]
    assert data["result"] is None


def test_400_handler(app, client):
    """Map BadRequest to a 400 error envelope that keeps its message."""

    @app.route("/bad-request")
    def bad_request():
        msg = "Invalid parameters"
        raise BadRequest(msg)

    response = client.get("/bad-request")
    data = response.get_json()

    assert response.status_code == 400
    assert data["status"] == "error"
    assert "Invalid parameters" in data["message"]
    assert data["result"] is None


def test_401_handler(app, client):
    """Map Unauthorized to a 401 error envelope that keeps its message."""

    @app.route("/unauthorized")
    def unauthorized():
        msg = "Invalid credentials"
        raise Unauthorized(msg)

    response = client.get("/unauthorized")
    data = response.get_json()

    assert response.status_code == 401
    assert data["status"] == "error"
    assert "Invalid credentials" in data["message"]
    assert data["result"] is None


def test_403_handler(app, client):
    """Map Forbidden to a 403 error envelope that keeps its message."""

    @app.route("/forbidden")
    def forbidden():
        msg = "Access denied"
        raise Forbidden(msg)

    response = client.get("/forbidden")
    data = response.get_json()

    assert response.status_code == 403
    assert data["status"] == "error"
    assert "Access denied" in data["message"]
    assert data["result"] is None


def test_500_handler(app, client):
    """Map InternalServerError to a 500 error envelope that keeps its message."""

    @app.route("/server-error")
    def server_error():
        msg = "Database connection failed"
        raise InternalServerError(msg)

    response = client.get("/server-error")
    data = response.get_json()

    assert response.status_code == 500
    assert data["status"] == "error"
    assert "Database connection failed" in data["message"]
    assert data["result"] is None


def test_generic_exception_handler(app, client):
    """Map any other exception to a 500 error envelope that keeps its message."""

    @app.route("/generic-error")
    def generic_error():
        msg = "Something went wrong"
        raise ValueError(msg)

    response = client.get("/generic-error")
    data = response.get_json()

    assert response.status_code == 500
    assert data["status"] == "error"
    assert "Something went wrong" in data["message"]
    assert data["result"] is None
