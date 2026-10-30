"""The UK economy routes answer 400 for a region .py's UK registry can't resolve."""

import json
from unittest.mock import MagicMock

import pytest
from flask import Flask

from policyengine_api.routes import economy_routes
from policyengine_api.services.economy_service import EconomyService

ACCEPTED_REGIONS = (
    "Accepted regions: uk; country/england, country/scotland, country/wales, "
    "country/northern_ireland or country/ni; "
    "constituency/<constituency name or GSS code>; "
    "local_authority/<local authority name or GSS code>."
)
ANNUAL_PATH = "/uk/economy/123/over/456"
BUDGET_WINDOW_PATH = "/uk/economy/123/over/456/budget-window"


@pytest.fixture
def collaborators(monkeypatch):
    """Serve the routes from a real service whose collaborators record every call."""
    recorded = MagicMock()
    monkeypatch.setattr(
        economy_routes,
        "economy_service",
        EconomyService(
            policy_service_=recorded.policies,
            reform_impacts_service_=recorded.reform_impacts,
            budget_window_cache_=recorded.budget_window_cache,
            simulation_entrypoint_=recorded.simulation_entrypoint,
        ),
    )
    return recorded


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(economy_routes.economy_bp)
    return app.test_client()


@pytest.mark.parametrize(
    "region", ["constituency", "parliamentary_constituency", "constituency/all"]
)
@pytest.mark.parametrize(
    "query",
    [
        f"{ANNUAL_PATH}?time_period=2026&region=",
        f"{BUDGET_WINDOW_PATH}?start_year=2026&window_size=3&region=",
    ],
    ids=["annual", "budget-window"],
)
def test_an_unresolvable_uk_region_gets_400_and_nothing_runs(
    client, collaborators, query, region
):
    response = client.get(query + region)

    assert response.status_code == 400
    assert json.loads(response.data) == {
        "status": "error",
        "message": f"Unknown UK region {region!r}. {ACCEPTED_REGIONS}",
        "result": None,
    }
    assert collaborators.mock_calls == []


def test_an_unresolvable_breakdown_region_gets_400_and_nothing_runs(
    client, collaborators
):
    response = client.get(
        f"{ANNUAL_PATH}?time_period=2026&breakdown=local_areas&region=constituency"
    )

    assert response.status_code == 400
    assert json.loads(response.data)["message"].startswith(
        "breakdown=local_areas needs region uk or a UK country"
    )
    assert collaborators.mock_calls == []
