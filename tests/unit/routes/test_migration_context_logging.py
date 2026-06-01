from unittest.mock import patch

from flask import Flask, Response

from policyengine_api.migration_logging import register_migration_request_logging


def _app():
    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.route("/readiness-check")
    def readiness_check():
        return Response("OK", status=200, mimetype="text/plain")

    register_migration_request_logging(app)
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
