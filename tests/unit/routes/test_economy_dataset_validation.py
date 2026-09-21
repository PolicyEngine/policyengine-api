import json
from unittest.mock import Mock, patch

from flask import Flask

from policyengine_api.routes.economy_routes import economy_bp


def _mock_economic_result():
    mock_result = Mock()
    mock_result.to_dict.return_value = {
        "status": "ok",
        "data": {"congressional_district_impact": {"districts": []}},
        "message": "Messages must not be returned for successful results",
    }
    return mock_result


def _client_with_economy_blueprint():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(economy_bp)
    return app.test_client()


@patch("policyengine_api.routes.economy_routes.economy_service.get_economic_impact")
def test_economy_route_rejects_dataset_query_parameter(
    mock_get_economic_impact,
):
    client = _client_with_economy_blueprint()

    response = client.get(
        "/us/economy/123/over/456?region=us&time_period=2026&dataset=enhanced_cps"
    )
    payload = json.loads(response.data)

    assert response.status_code == 400
    assert payload["status"] == "error"
    assert "dataset: Extra inputs are not permitted" in payload["message"]
    mock_get_economic_impact.assert_not_called()


@patch("policyengine_api.routes.economy_routes.economy_service.get_economic_impact")
def test_economy_route_rejects_removed_breakdown_flag(mock_get_economic_impact):
    client = _client_with_economy_blueprint()

    response = client.get(
        "/us/economy/123/over/456"
        "?region=us&time_period=2026&include_district_breakdowns=true"
    )
    payload = json.loads(response.data)

    assert response.status_code == 400
    assert payload["status"] == "error"
    assert (
        "include_district_breakdowns: Extra inputs are not permitted"
        in payload["message"]
    )
    mock_get_economic_impact.assert_not_called()


@patch("policyengine_api.routes.economy_routes.economy_service.get_economic_impact")
def test_economy_route_returns_bad_gateway_for_failed_simulation(
    mock_get_economic_impact,
):
    error_message = "Simulation entrypoint execution failed: worker exited"
    mock_result = Mock()
    mock_result.to_dict.return_value = {
        "status": "error",
        "data": None,
        "message": error_message,
    }
    mock_get_economic_impact.return_value = mock_result
    client = _client_with_economy_blueprint()

    response = client.get("/us/economy/123/over/456?region=us&time_period=2026")
    payload = json.loads(response.data)

    assert response.status_code == 502
    assert payload == {
        "status": "error",
        "message": error_message,
        "result": None,
    }


@patch("policyengine_api.routes.economy_routes.economy_service.get_economic_impact")
def test_economy_route_keeps_computing_response_as_http_200(mock_get_economic_impact):
    mock_result = Mock()
    mock_result.to_dict.return_value = {
        "status": "computing",
        "data": None,
        "message": None,
    }
    mock_get_economic_impact.return_value = mock_result
    client = _client_with_economy_blueprint()

    response = client.get("/us/economy/123/over/456?region=us&time_period=2026")

    assert response.status_code == 200


@patch(
    "policyengine_api.routes.economy_routes.economy_service.get_budget_window_economic_impact"
)
def test_budget_window_route_rejects_dataset_query_parameter(
    mock_get_budget_window_economic_impact,
):
    client = _client_with_economy_blueprint()

    response = client.get(
        "/us/economy/123/over/456/budget-window"
        "?region=us&start_year=2026&window_size=2&dataset=enhanced_cps"
    )
    payload = json.loads(response.data)

    assert response.status_code == 400
    assert payload["status"] == "error"
    assert "dataset: Extra inputs are not permitted" in payload["message"]
    mock_get_budget_window_economic_impact.assert_not_called()
