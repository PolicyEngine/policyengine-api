import json
from unittest.mock import Mock, patch


@patch(
    "policyengine_api.routes.economy_routes.economy_service.get_budget_window_economic_impact"
)
def test_budget_window_route_rejects_cliff_target(
    mock_get_budget_window_economic_impact, rest_client
):
    response = rest_client.get(
        "/us/economy/123/over/456/budget-window"
        "?region=us&start_year=2026&window_size=10&target=cliff"
    )

    data = json.loads(response.data)

    assert response.status_code == 400
    assert data["status"] == "error"
    assert "target=general" in data["message"]
    mock_get_budget_window_economic_impact.assert_not_called()


@patch(
    "policyengine_api.routes.economy_routes.economy_service.get_budget_window_economic_impact"
)
def test_budget_window_route_requires_window_size(
    mock_get_budget_window_economic_impact, rest_client
):
    response = rest_client.get(
        "/us/economy/123/over/456/budget-window?region=us&start_year=2026"
    )

    data = json.loads(response.data)

    assert response.status_code == 400
    assert data["status"] == "error"
    assert "window_size" in data["message"]
    mock_get_budget_window_economic_impact.assert_not_called()


@patch(
    "policyengine_api.routes.economy_routes.economy_service.get_budget_window_economic_impact"
)
def test_budget_window_route_requires_integer_window_size(
    mock_get_budget_window_economic_impact, rest_client
):
    response = rest_client.get(
        "/us/economy/123/over/456/budget-window"
        "?region=us&start_year=2026&window_size=abc"
    )

    data = json.loads(response.data)

    assert response.status_code == 400
    assert data["status"] == "error"
    assert "window_size must be an integer" == data["message"]
    mock_get_budget_window_economic_impact.assert_not_called()


def test_budget_window_route_rejects_oversized_window(rest_client):
    response = rest_client.get(
        "/us/economy/123/over/456/budget-window"
        "?region=us&start_year=2026&window_size=999"
    )

    data = json.loads(response.data)

    assert response.status_code == 400
    assert data["status"] == "error"
    assert "window_size must be between 1 and" in data["message"]


def test_budget_window_route_rejects_end_year_after_2099(rest_client):
    response = rest_client.get(
        "/us/economy/123/over/456/budget-window"
        "?region=us&start_year=2090&window_size=20"
    )

    data = json.loads(response.data)

    assert response.status_code == 400
    assert data["status"] == "error"
    assert "budget-window end_year must be 2099 or earlier" == data["message"]


@patch(
    "policyengine_api.routes.economy_routes.economy_service.get_budget_window_economic_impact"
)
def test_budget_window_route_passes_version_to_service(
    mock_get_budget_window_economic_impact, rest_client
):
    mock_result = Mock()
    mock_result.to_dict.return_value = {
        "status": "ok",
        "message": None,
        "data": {
            "kind": "budgetWindow",
            "startYear": "2026",
            "endYear": "2027",
            "windowSize": 2,
            "annualImpacts": [],
            "totals": {},
        },
        "progress": 100,
        "completed_years": ["2026", "2027"],
        "computing_years": [],
        "queued_years": [],
        "error": None,
    }
    mock_get_budget_window_economic_impact.return_value = mock_result

    response = rest_client.get(
        "/us/economy/123/over/456/budget-window"
        "?region=us&start_year=2026&window_size=2&version=1.2.3"
    )

    data = json.loads(response.data)

    assert response.status_code == 200
    assert data["status"] == "ok"
    mock_get_budget_window_economic_impact.assert_called_once_with(
        country_id="us",
        policy_id=123,
        baseline_policy_id=456,
        region="us",
        dataset="default",
        start_year="2026",
        window_size=2,
        options={},
        api_version="1.2.3",
        target="general",
    )
