from unittest.mock import patch

from fastapi.testclient import TestClient
from flask import Flask, Response

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.migration_logging import register_migration_request_logging


def _app():
    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.route("/readiness-check")
    def readiness_check():
        return Response("OK", status=200, mimetype="text/plain")

    register_migration_request_logging(app)
    return app


def _app_without_migration_logging():
    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.route("/fallback")
    def fallback():
        return Response("fallback", status=200, mimetype="text/plain")

    return app


def test_request_logging_includes_migration_context():
    with patch("policyengine_api.migration_logging.logger") as mock_logger:
        response = _app().test_client().get("/readiness-check")

    assert response.status_code == 200
    log_payload = mock_logger.log_struct.call_args.args[0]
    assert log_payload["message"] == "API request served"
    assert log_payload["path"] == "/readiness-check"
    assert log_payload["status_code"] == 200
    assert log_payload["migration"]["route_group"] == "health"
    assert log_payload["migration"]["api_host_backend"] == "app_engine"
    assert log_payload["migration"]["route_impl"] == "flask_fallback"


def test_request_logging_failure_does_not_change_response():
    with patch(
        "policyengine_api.migration_logging.logger.log_struct",
        side_effect=RuntimeError("logging failed"),
    ):
        response = _app().test_client().get("/readiness-check")

    assert response.status_code == 200
    assert response.data == b"OK"


def test_request_logging_runs_for_asgi_fallback_routes():
    with patch("policyengine_api.migration_logging.logger") as mock_logger:
        response = TestClient(create_asgi_app(_app())).get("/readiness-check")

    assert response.status_code == 200
    assert response.content == b"OK"
    log_payload = mock_logger.log_struct.call_args.args[0]
    assert log_payload["path"] == "/readiness-check"
    assert log_payload["migration"]["route_group"] == "health"


def test_request_logging_runs_for_fastapi_native_health_routes(monkeypatch):
    monkeypatch.setenv("API_HOST_BACKEND", "cloud_run")

    with patch("policyengine_api.migration_logging.logger") as mock_logger:
        response = TestClient(create_asgi_app(_app())).get(
            "/health",
            headers={"X-Request-ID": "request-123"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
    log_payload = mock_logger.log_struct.call_args.args[0]
    assert log_payload["message"] == "API request served"
    assert log_payload["request_id"] == "request-123"
    assert log_payload["path"] == "/health"
    assert log_payload["status_code"] == 200
    assert log_payload["country_id"] is None
    assert log_payload["migration"]["route_group"] == "health"
    assert log_payload["migration"]["api_host_backend"] == "cloud_run"
    assert log_payload["migration"]["route_impl"] == "flask_fallback"


def test_fastapi_native_logging_failure_does_not_change_response():
    with patch(
        "policyengine_api.migration_logging.logger.log_struct",
        side_effect=RuntimeError("logging failed"),
    ):
        response = TestClient(create_asgi_app(_app())).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_asgi_shell_does_not_log_unregistered_flask_fallback_routes():
    with patch("policyengine_api.migration_logging.logger") as mock_logger:
        response = TestClient(create_asgi_app(_app_without_migration_logging())).get(
            "/fallback"
        )

    assert response.status_code == 200
    assert response.content == b"fallback"
    mock_logger.log_struct.assert_not_called()
