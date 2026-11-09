"""Society-wide requests for a year outside the country's years get 400.

The body is the one the app reads (PolicyEngine/policyengine-app-v2#1452): the
code DATASET_YEAR_UNAVAILABLE in ``errors`` and a readable top-level
``message``. The 400 comes before anything is read from storage or sent to
the simulation service, so a stored result for the year is not returned.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from flask import Flask

from policyengine_api import worker_spm
from policyengine_api.routes import economy_routes
from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.reform_impacts import ReformImpactCache
from policyengine_api.services.economic_impact_request import EconomicImpactRequest
from policyengine_api.services.economy_service import EconomyService
from policyengine_api.services.reform_impacts_service import (
    ReformImpactExecution,
    ReformImpactsService,
)
from tests.fixtures.services.economy_service import ECONOMY_SERVICE_LOGGER_MODULES

STORED_EXECUTION_ID = "stored-impact-job"
STORED_IMPACT = {"budget": {"budgetary_impact": 1_000_000}}


def unavailable_year_body(country: str, first: int, last: int, year: str) -> dict:
    """Return the 400 body the app expects for ``year``."""
    message = (
        f"{country} results are available for {first} to {last}. {year} is "
        f"outside the years the current {country} model and data cover."
    )
    return {
        "status": "error",
        "message": message,
        "result": None,
        "errors": [{"code": "DATASET_YEAR_UNAVAILABLE", "message": message}],
    }


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


def _client() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(economy_routes.economy_bp)
    return app.test_client()


@pytest.mark.parametrize(
    ("country_id", "year", "expected_body"),
    [
        ("us", "2022", unavailable_year_body("US", 2024, 2036, "2022")),
        ("us", "2023", unavailable_year_body("US", 2024, 2036, "2023")),
        ("us", "2037", unavailable_year_body("US", 2024, 2036, "2037")),
        ("uk", "2023", unavailable_year_body("UK", 2024, 2032, "2023")),
        ("uk", "2033", unavailable_year_body("UK", 2024, 2032, "2033")),
    ],
)
@pytest.mark.parametrize("method", ["GET", "DELETE"])
def test_an_annual_year_outside_the_countrys_years_gets_400_and_nothing_runs(
    collaborators, country_id, year, expected_body, method
):
    response = _client().open(
        f"/{country_id}/economy/123/over/456",
        method=method,
        query_string={"region": country_id, "time_period": year},
    )

    assert response.status_code == 400
    body = json.loads(response.data)
    assert body == expected_body
    assert body["errors"][0]["code"] == "DATASET_YEAR_UNAVAILABLE"
    assert collaborators.mock_calls == []


@pytest.mark.parametrize(
    ("country_id", "start_year", "window_size", "expected_body"),
    [
        ("us", "2023", "3", unavailable_year_body("US", 2024, 2036, "2023")),
        ("us", "2037", "1", unavailable_year_body("US", 2024, 2036, "2037")),
        ("uk", "2023", "2", unavailable_year_body("UK", 2024, 2032, "2023")),
    ],
)
def test_a_budget_window_starting_outside_the_countrys_years_gets_400(
    collaborators, country_id, start_year, window_size, expected_body
):
    response = _client().get(
        f"/{country_id}/economy/123/over/456/budget-window",
        query_string={
            "region": country_id,
            "start_year": start_year,
            "window_size": window_size,
        },
    )

    assert response.status_code == 400
    assert json.loads(response.data) == expected_body
    assert collaborators.mock_calls == []


@pytest.fixture
def stored_us_impact(monkeypatch, request):
    """Store a finished US impact for ``request.param`` and serve the routes.

    Return the stored-impact cache and the simulation service stand-in.
    """
    monkeypatch.setattr(worker_spm, "normalize_spm_selection", lambda *_: None)
    gateway = Mock()

    def resolve_app_name(
        _country_id: str, version: str | None = None, **_kwargs: object
    ) -> tuple[str, str | None]:
        return "test-worker", version

    gateway.resolve_app_name.side_effect = resolve_app_name
    cache = ReformImpactCache(
        InMemoryCacheBackend(), CacheNamespace("test", "unavailable-years")
    )
    impacts = ReformImpactsService(cache)
    policies = Mock()
    service = EconomyService(
        policy_service_=policies,
        reform_impacts_service_=impacts,
        simulation_entrypoint_=gateway,
    )
    # Stored the way an earlier release, which offered the year, stored it.
    setup = service._build_economic_impact_setup_options(
        EconomicImpactRequest(
            country_id="us",
            policy_id=1,
            baseline_policy_id=2,
            region="us",
            dataset="default",
            options={},
            api_version="1.0.0",
        ),
        time_period=request.param,
    )
    service._resolve_runtime_bundle_for_setup_options(setup)
    impacts.set_reform_impact(
        service._reform_impact_identity(setup),
        ReformImpactExecution(execution_id=STORED_EXECUTION_ID, start_time=None),
        options=setup.options,
        status="ok",
        reform_impact_json=STORED_IMPACT,
    )
    gateway.reset_mock()
    monkeypatch.setattr(economy_routes, "economy_service", service)
    for module_name in ECONOMY_SERVICE_LOGGER_MODULES:
        monkeypatch.setattr(f"{module_name}.logger", Mock())
    return SimpleNamespace(cache=cache, gateway=gateway, policies=policies)


@pytest.mark.parametrize("stored_us_impact", ["2022"], indirect=True)
def test_a_stored_result_for_an_unavailable_year_is_not_returned(stored_us_impact):
    response = _client().get(
        "/us/economy/1/over/2",
        query_string={"region": "us", "time_period": "2022", "version": "1.0.0"},
    )

    assert response.status_code == 400
    assert response.json == unavailable_year_body("US", 2024, 2036, "2022")
    assert stored_us_impact.gateway.mock_calls == []
    assert stored_us_impact.policies.mock_calls == []
    stored = stored_us_impact.cache.get_by_execution_id(STORED_EXECUTION_ID)
    assert stored.status == "ok"
    assert stored.reform_impact_json == STORED_IMPACT


@pytest.mark.parametrize("stored_us_impact", ["2024"], indirect=True)
def test_a_stored_result_for_an_offered_year_is_returned(stored_us_impact):
    """The same request for 2024 answers from the stored result."""
    response = _client().get(
        "/us/economy/1/over/2",
        query_string={"region": "us", "time_period": "2024", "version": "1.0.0"},
    )

    assert response.status_code == 200, response.json
    assert response.json["status"] == "ok"
    assert response.json["result"]["budget"] == STORED_IMPACT["budget"]
