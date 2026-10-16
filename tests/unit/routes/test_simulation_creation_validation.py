"""Pin how the v1 simulation-creation route validates and reports failures."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import NotFound

from policyengine_api.routes import simulation_routes

VALID_PAYLOAD = {
    "population_id": "1",
    "population_type": "household",
    "policy_id": 2,
}


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(simulation_routes.simulation_bp)
    return app.test_client()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (None, "Payload missing from request"),
        ({**VALID_PAYLOAD, "population_id": ""}, "population_id is required"),
        ({**VALID_PAYLOAD, "population_type": None}, "population_type is required"),
        (
            {**VALID_PAYLOAD, "population_type": "region"},
            "population_type must be &#39;household&#39; or &#39;geography&#39;",
        ),
        ({**VALID_PAYLOAD, "policy_id": None}, "policy_id is required"),
        ({**VALID_PAYLOAD, "policy_id": "2"}, "policy_id must be an integer"),
        (
            {"population_type": "region", "policy_id": "2"},
            "population_id is required",
        ),
        (
            {"population_id": "1", "population_type": "region"},
            "population_type must be &#39;household&#39; or &#39;geography&#39;",
        ),
    ],
)
def test_invalid_payloads_are_bad_requests_before_any_write(
    client,
    payload: object,
    message: str,
) -> None:
    with patch.object(simulation_routes, "simulation_service") as service:
        response = client.post(
            "/us/simulation",
            data="null" if payload is None else None,
            json=payload if payload is not None else None,
            content_type="application/json",
        )

    assert response.status_code == 400
    assert message in response.get_data(as_text=True)
    assert not service.mock_calls


@pytest.mark.parametrize(
    ("created", "status_code", "message"),
    [
        (True, 201, "Simulation created successfully"),
        (False, 200, "Simulation already exists"),
    ],
)
def test_us_payload_returns_the_serialized_simulation(
    client,
    created,
    status_code: int,
    message: str,
) -> None:
    with (
        patch.object(simulation_routes, "simulation_service") as service,
        patch.object(
            simulation_routes,
            "_serialize_v1_simulation",
            return_value={"id": 7},
        ),
    ):
        service.get_or_create_simulation.return_value = SimpleNamespace(
            simulation=object(), created=created
        )
        response = client.post("/us/simulation", json=VALID_PAYLOAD)

    assert response.status_code == status_code
    assert response.get_json() == {
        "status": "ok",
        "message": message,
        "result": {"id": 7},
    }
    service.get_or_create_simulation.assert_called_once_with(
        country_id="us",
        population_id="1",
        population_type="household",
        policy_id=2,
    )


def test_service_http_errors_pass_through_unlogged(client) -> None:
    with (
        patch.object(simulation_routes, "simulation_service") as service,
        patch.object(simulation_routes, "current_app", new=MagicMock()) as current_app,
    ):
        service.get_or_create_simulation.side_effect = NotFound("missing policy")
        response = client.post("/us/simulation", json=VALID_PAYLOAD)

    assert response.status_code == 404
    assert "missing policy" in response.get_data(as_text=True)
    assert not current_app.logger.mock_calls


def test_service_value_errors_become_logged_bad_requests(client) -> None:
    error = ValueError("unknown household")
    with (
        patch.object(simulation_routes, "simulation_service") as service,
        patch.object(simulation_routes, "current_app", new=MagicMock()) as current_app,
    ):
        service.get_or_create_simulation.side_effect = error
        response = client.post("/us/simulation", json=VALID_PAYLOAD)

    assert response.status_code == 400
    assert "Failed to create simulation: unknown household" in response.get_data(
        as_text=True
    )
    current_app.logger.warning.assert_called_once_with(
        "Bad request creating simulation for country %s: %s", "us", error
    )


def test_unexpected_service_errors_are_logged_and_raised(client) -> None:
    error = RuntimeError("database exploded")
    with (
        patch.object(simulation_routes, "simulation_service") as service,
        patch.object(simulation_routes, "current_app", new=MagicMock()) as current_app,
    ):
        service.get_or_create_simulation.side_effect = error
        with pytest.raises(RuntimeError) as raised:
            client.post("/us/simulation", json=VALID_PAYLOAD)

    assert raised.value is error
    current_app.logger.exception.assert_called_once_with(
        "Unexpected error creating simulation for country %s", "us"
    )
