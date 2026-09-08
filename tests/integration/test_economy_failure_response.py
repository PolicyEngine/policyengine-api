from datetime import datetime
from unittest.mock import MagicMock

from flask import Flask
import httpx

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.libs.simulation_entrypoint import SimulationEntrypointClient
from policyengine_api.routes import economy_routes
from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.reform_impacts import ReformImpactCache
from policyengine_api.services.economy_service import EconomyService
from policyengine_api.services.reform_impacts_service import ReformImpactsService


def test_failed_economy_job_returns_and_caches_bad_gateway_response(monkeypatch):
    for variable_name in (
        "GATEWAY_AUTH_ISSUER",
        "GATEWAY_AUTH_AUDIENCE",
        "GATEWAY_AUTH_CLIENT_ID",
        "GATEWAY_AUTH_CLIENT_SECRET",
        "GATEWAY_AUTH_CLIENT_SECRET_RESOURCE",
        "GATEWAY_AUTH_REQUIRED",
    ):
        monkeypatch.delenv(variable_name, raising=False)
    monkeypatch.setenv("OLD_SIMULATION_GATEWAY_URL", "https://simulation.test")

    runtime_app_name = "policyengine-simulation-test"
    execution_id = "failed-execution"
    job_poll_count = 0

    def simulation_response(request: httpx.Request) -> httpx.Response:
        nonlocal job_poll_count
        if request.url.path == f"/jobs/{execution_id}":
            job_poll_count += 1
            return httpx.Response(
                500,
                json={
                    "status": "failed",
                    "error": "worker exited",
                },
            )
        if request.url.path == "/versions/policyengine":
            from policyengine_api.constants import POLICYENGINE_VERSION

            return httpx.Response(
                200,
                json={POLICYENGINE_VERSION: runtime_app_name},
            )
        raise AssertionError(f"Unexpected simulation request: {request.url}")

    cache = ReformImpactCache(
        InMemoryCacheBackend(),
        CacheNamespace(environment="test", service="api"),
    )
    reform_impacts = ReformImpactsService(cache)
    simulation_gateway = SimulationEntrypointClient(entrypoint="old_gateway_direct")
    simulation_gateway.client.close()
    simulation_gateway.client = httpx.Client(
        base_url="https://simulation.test",
        transport=httpx.MockTransport(simulation_response),
    )
    service = EconomyService(
        policy_service_=MagicMock(),
        reform_impacts_service_=reform_impacts,
        simulation_entrypoint_=simulation_gateway,
    )

    caller_version = COUNTRY_PACKAGE_VERSIONS["us"]
    setup = service._build_economic_impact_setup_options(
        country_id="us",
        policy_id=123,
        baseline_policy_id=456,
        region="us",
        dataset="default",
        time_period="2026",
        options={},
        api_version=caller_version,
        target="general",
    )
    resolved_options_hash = service._build_options_hash(
        options=setup.options,
        model_version=setup.model_version,
        dataset=setup.dataset,
        data_version=setup.data_version,
        policyengine_version=setup.policyengine_version,
        runtime_app_name=runtime_app_name,
    )
    reform_impacts.set_reform_impact(
        country_id=setup.country_id,
        policy_id=setup.reform_policy_id,
        baseline_policy_id=setup.baseline_policy_id,
        region=setup.region,
        dataset=setup.dataset,
        time_period=setup.time_period,
        options=setup.options,
        options_hash=resolved_options_hash,
        status="computing",
        api_version=setup.api_version,
        reform_impact_json={},
        start_time=datetime(2026, 1, 1),
        execution_id=execution_id,
    )

    monkeypatch.setattr(economy_routes, "economy_service", service)
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(economy_routes.economy_bp)
    client = app.test_client()
    path = "/us/economy/123/over/456"
    query = {
        "region": "us",
        "time_period": "2026",
        "version": caller_version,
    }

    first_response = client.get(path, query_string=query)
    second_response = client.get(path, query_string=query)

    expected_payload = {
        "status": "error",
        "message": "Simulation entrypoint execution failed: worker exited",
        "result": None,
    }
    assert first_response.status_code == 502
    assert first_response.get_json() == expected_payload
    assert second_response.status_code == 502
    assert second_response.get_json() == expected_payload
    assert job_poll_count == 1

    cached_impact = cache.get_by_execution_id(execution_id)
    assert cached_impact is not None
    assert cached_impact.status == "error"
    assert cached_impact.message == expected_payload["message"]

    simulation_gateway.client.close()
