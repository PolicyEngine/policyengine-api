"""Typed worker year errors survive real HTTP client/service/Flask polling."""

from flask import Flask
import httpx
import pytest

from policyengine_api import worker_spm
from policyengine_api.libs.simulation_entrypoint import SimulationEntrypointClient
from policyengine_api.routes import economy_routes
from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.reform_impacts import ReformImpactCache
from policyengine_api.services import economy_service as economy_module
from policyengine_api.services.budget_window_cache import BudgetWindowCache
from policyengine_api.services.economy_service import EconomyService
from policyengine_api.services.reform_impacts_service import ReformImpactsService


SELECTION = {
    "forecast_content_sha256": "a" * 64,
    "scenario": "baseline",
    "geography_kind": "national",
    "geography_id": None,
    "county_vintage": "2020",
    "as_of": None,
}
YEAR_ERROR = {
    "code": "SPM_YEAR_UNAVAILABLE",
    "message": "Forecast has no entry for 2036",
}


@pytest.mark.parametrize("upstream_status", [400, 422])
@pytest.mark.parametrize("budget_window", [False, True], ids=["annual", "window"])
def test_typed_worker_year_error_survives_repeated_http_polls(
    monkeypatch, upstream_status, budget_window
):
    # Certification is synthetic; the HTTP consumer, routes and both caches are
    # real. No worker execution or dataset loading is needed for this boundary.
    monkeypatch.setattr(worker_spm, "normalize_spm_selection", lambda *_: SELECTION)
    monkeypatch.setattr(economy_module, "COUNTRY_PACKAGE_VERSIONS", {"us": "1.0.0"})
    monkeypatch.setattr(economy_module, "POLICYENGINE_VERSION", "5.3.1")
    job_id = "unsupported-year-job"
    job_path = f"/budget-window-jobs/{job_id}" if budget_window else f"/jobs/{job_id}"
    received = []

    def transport(request):
        received.append((request.method, request.url.path))
        assert request.method == "GET", "Polling must not submit a replacement job"
        if request.url.path == "/versions":
            return httpx.Response(
                200,
                json={
                    "policyengine": {"5.3.1": "test-worker"},
                    "spm_capabilities": {
                        "5.3.1": {
                            "contract_version": "canonical-spm-v1",
                            "defaults": SELECTION,
                        }
                    },
                },
            )
        if request.url.path == "/versions/policyengine":
            return httpx.Response(200, json={"5.3.1": "test-worker"})
        assert request.url.path == job_path
        return httpx.Response(
            upstream_status,
            json={"status": "error", "errors": [YEAR_ERROR]},
        )

    gateway = object.__new__(SimulationEntrypointClient)
    gateway.base_url = "https://worker.invalid"
    backend = InMemoryCacheBackend()
    namespace = CacheNamespace("test", "typed-year-worker-polling")
    annual_cache = ReformImpactCache(backend, namespace)
    annual_impacts = ReformImpactsService(annual_cache)
    window_cache = BudgetWindowCache(backend, namespace)
    service = EconomyService(
        reform_impacts_service_=annual_impacts,
        budget_window_cache_=window_cache,
        simulation_entrypoint_=gateway,
    )
    monkeypatch.setattr(economy_routes, "economy_service", service)
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(economy_routes.economy_bp)

    with httpx.Client(transport=httpx.MockTransport(transport)) as gateway.client:
        setup = service._build_economic_impact_setup_options(
            country_id="us",
            policy_id=1,
            baseline_policy_id=2,
            region="us",
            dataset="default",
            time_period="budget_window:2035:2" if budget_window else "2036",
            options={},
            api_version="1.0.0",
        )
        if budget_window:
            cache_key = service._build_budget_window_cache_key(setup)
            window_cache.store_batch_job_id(cache_key, job_id)
            url = "/us/economy/1/over/2/budget-window"
            query = {"start_year": "2035", "window_size": "2"}
        else:
            service._resolve_runtime_bundle_for_setup_options(setup)
            annual_impacts.set_reform_impact(
                country_id=setup.country_id,
                policy_id=setup.reform_policy_id,
                baseline_policy_id=setup.baseline_policy_id,
                region=setup.region,
                dataset=setup.dataset,
                time_period=setup.time_period,
                options=setup.options,
                options_hash=setup.options_hash,
                status="computing",
                api_version=setup.api_version,
                reform_impact_json={},
                start_time=None,
                execution_id=job_id,
            )
            url = "/us/economy/1/over/2"
            query = {"time_period": "2036"}

        received.clear()
        for _ in range(2):
            response = app.test_client().get(
                url,
                query_string={"region": "us", "version": "1.0.0", **query},
            )
            assert response.status_code == 400, response.json
            assert response.json == {
                "status": "error",
                "result": None,
                "message": YEAR_ERROR["message"],
                "errors": [YEAR_ERROR],
            }
            if budget_window:
                assert window_cache.get_completed_result(cache_key) is None
                assert window_cache.get_batch_job_id(cache_key) == job_id
            else:
                stored = annual_cache.get_by_execution_id(job_id)
                assert stored.status == "computing"
                assert stored.reform_impact_json == {}
                assert stored.message is None

    assert received.count(("GET", job_path)) == 2
