"""Regression tests for issue #3448.

simulation_routes and report_output_routes caught every Exception and
converted it to BadRequest (400). That masked real 500s (DB errors,
coding bugs) and hid tracebacks. The fix: only ValueError /
pydantic.ValidationError / jsonschema.ValidationError become 400;
everything else propagates as 500 with logger.exception().
"""

from unittest.mock import patch

from flask import Flask

from policyengine_api.routes.report_output_routes import report_output_bp
from policyengine_api.routes.simulation_routes import simulation_bp


def _client_with(*blueprints):
    app = Flask(__name__)
    app.config["TESTING"] = True
    # Required so werkzeug propagates exceptions to response as 500
    # rather than reraising in the test client.
    app.config["PROPAGATE_EXCEPTIONS"] = False
    for bp in blueprints:
        app.register_blueprint(bp)
    return app.test_client()


def test_simulation_create_runtime_error_becomes_500():
    client = _client_with(simulation_bp)
    with patch(
        "policyengine_api.routes.simulation_routes.simulation_service.find_existing_simulation",
        side_effect=RuntimeError("db went away"),
    ):
        response = client.post(
            "/us/simulation",
            json={
                "population_id": "abc",
                "population_type": "household",
                "policy_id": 1,
            },
        )
    assert response.status_code == 500


def test_simulation_create_value_error_still_400():
    client = _client_with(simulation_bp)
    with patch(
        "policyengine_api.routes.simulation_routes.simulation_service.find_existing_simulation",
        side_effect=ValueError("bad input"),
    ):
        response = client.post(
            "/us/simulation",
            json={
                "population_id": "abc",
                "population_type": "household",
                "policy_id": 1,
            },
        )
    assert response.status_code == 400


def test_report_create_runtime_error_becomes_500():
    client = _client_with(report_output_bp)
    with patch(
        "policyengine_api.routes.report_output_routes.report_output_service.find_existing_report_output",
        side_effect=RuntimeError("db went away"),
    ):
        response = client.post(
            "/us/report",
            json={"simulation_1_id": 1, "year": "2025"},
        )
    assert response.status_code == 500


def test_report_create_value_error_still_400():
    client = _client_with(report_output_bp)
    with patch(
        "policyengine_api.routes.report_output_routes.report_output_service.find_existing_report_output",
        side_effect=ValueError("bad input"),
    ):
        response = client.post(
            "/us/report",
            json={"simulation_1_id": 1, "year": "2025"},
        )
    assert response.status_code == 400
