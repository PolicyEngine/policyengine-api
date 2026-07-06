import json
from unittest.mock import Mock, patch

from flask import Flask

from policyengine_api.routes.economy_routes import economy_bp


def _mock_economic_result():
    mock_result = Mock()
    mock_result.to_dict.return_value = {
        "status": "ok",
        "data": {"congressional_district_impact": {"districts": []}},
    }
    return mock_result


def _client_with_economy_blueprint():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(economy_bp)
    return app.test_client()


@patch("policyengine_api.routes.economy_routes.economy_service.get_economic_impact")
def test_economy_route_returns_bad_request_for_dataset_validation_error(
    mock_get_economic_impact,
):
    mock_get_economic_impact.side_effect = ValueError(
        "Dataset 'enhanced_cps' is deprecated."
    )
    client = _client_with_economy_blueprint()

    response = client.get(
        "/us/economy/123/over/456?region=us&time_period=2026&dataset=enhanced_cps"
    )
    payload = json.loads(response.data)

    assert response.status_code == 400
    assert payload["status"] == "error"
    assert "enhanced_cps" in payload["message"]


@patch("policyengine_api.routes.economy_routes.economy_service.get_economic_impact")
def test_economy_route_ignores_deprecated_breakdown_flag(mock_get_economic_impact):
    mock_get_economic_impact.return_value = _mock_economic_result()
    client = _client_with_economy_blueprint()

    response = client.get(
        "/us/economy/123/over/456"
        "?region=us&time_period=2026&include_district_breakdowns=true"
    )
    payload = json.loads(response.data)

    assert response.status_code == 200
    assert payload["status"] == "ok"
    mock_get_economic_impact.assert_called_once()
    assert mock_get_economic_impact.call_args.kwargs["dataset"] == "default"
    assert mock_get_economic_impact.call_args.kwargs["options"] == {}


@patch(
    "policyengine_api.routes.economy_routes.economy_service.get_budget_window_economic_impact"
)
def test_budget_window_route_returns_bad_request_for_dataset_validation_error(
    mock_get_budget_window_economic_impact,
):
    mock_get_budget_window_economic_impact.side_effect = ValueError(
        "Dataset 'enhanced_cps' is deprecated."
    )
    client = _client_with_economy_blueprint()

    response = client.get(
        "/us/economy/123/over/456/budget-window"
        "?region=us&start_year=2026&window_size=2&dataset=enhanced_cps"
    )
    payload = json.loads(response.data)

    assert response.status_code == 400
    assert payload["status"] == "error"
    assert "enhanced_cps" in payload["message"]
