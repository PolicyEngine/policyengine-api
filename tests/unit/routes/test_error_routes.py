import pytest
from flask import Flask
from policyengine_api.routes.error_routes import error_bp
from werkzeug.exceptions import (
    NotFound,
    BadRequest,
    Unauthorized,
    Forbidden,
    InternalServerError,
)


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
    """Test 404 Not Found error handling"""

    @app.route("/nonexistent")
    def nonexistent():
        raise NotFound("Custom not found message")

    response = client.get("/nonexistent")
    data = response.get_json()

    assert response.status_code == 404
    assert data["status"] == "error"
    assert "Custom not found message" in data["message"]
    assert data["result"] is None


def test_400_handler(app, client):
    """Test 400 Bad Request error handling"""

    @app.route("/bad-request")
    def bad_request():
        raise BadRequest("Invalid parameters")

    response = client.get("/bad-request")
    data = response.get_json()

    assert response.status_code == 400
    assert data["status"] == "error"
    assert "Invalid parameters" in data["message"]
    assert data["result"] is None


def test_401_handler(app, client):
    """Test 401 Unauthorized error handling"""

    @app.route("/unauthorized")
    def unauthorized():
        raise Unauthorized("Invalid credentials")

    response = client.get("/unauthorized")
    data = response.get_json()

    assert response.status_code == 401
    assert data["status"] == "error"
    assert "Invalid credentials" in data["message"]
    assert data["result"] is None


def test_403_handler(app, client):
    """Test 403 Forbidden error handling"""

    @app.route("/forbidden")
    def forbidden():
        raise Forbidden("Access denied")

    response = client.get("/forbidden")
    data = response.get_json()

    assert response.status_code == 403
    assert data["status"] == "error"
    assert "Access denied" in data["message"]
    assert data["result"] is None


def test_500_handler(app, client):
    """Test 500 Internal Server Error handling"""

    @app.route("/server-error")
    def server_error():
        raise InternalServerError("Database connection failed")

    response = client.get("/server-error")
    data = response.get_json()

    assert response.status_code == 500
    assert data["status"] == "error"
    assert "Database connection failed" in data["message"]
    assert data["result"] is None


def test_generic_exception_handler(app, client):
    """Test handling of generic exceptions"""

    @app.route("/generic-error")
    def generic_error():
        raise ValueError("Something went wrong")

    response = client.get("/generic-error")
    data = response.get_json()

    assert response.status_code == 500
    assert data["status"] == "error"
    assert "Something went wrong" in data["message"]
    assert data["result"] is None
