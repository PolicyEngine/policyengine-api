"""Typed worker failures become durable terminal HTTP polling responses."""

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


def segmented_result(year, invalid_side=None):
    receipt = {
        "forecast_id": "test-only",
        "forecast_sha256": SELECTION["forecast_content_sha256"],
        "scenario": SELECTION["scenario"],
        "geography_kind": SELECTION["geography_kind"],
        "runtime_versions": {},
        "years": {year: {}},
        "geographies": [],
        "composition_method": "classified",
        "storage_method": "formula",
    }
    result = {
        "year": year,
        "spm_config": SELECTION,
        "spm_provenance": {
            "baseline": [dict(receipt), dict(receipt)],
            "reform": [dict(receipt), dict(receipt)],
        },
    }
    if invalid_side:
        result["spm_provenance"][invalid_side][1]["years"] = {"2000": {}}
    return result


@pytest.mark.parametrize(
    "failure", [400, 422, "segmented-baseline", "segmented-reform"]
)
@pytest.mark.parametrize("budget_window", [False, True], ids=["annual", "window"])
def test_typed_worker_error_is_terminal_and_replays_after_service_recreation(
    monkeypatch, failure, budget_window
):
    # Certification is synthetic; the HTTP consumer, routes and both caches are
    # real. No worker execution or dataset loading is needed for this boundary.
    monkeypatch.setattr(worker_spm, "normalize_spm_selection", lambda *_: SELECTION)
    monkeypatch.setattr(economy_module, "COUNTRY_PACKAGE_VERSIONS", {"us": "1.0.0"})
    monkeypatch.setattr(economy_module, "POLICYENGINE_VERSION", "5.3.1")
    job_id = "unsupported-year-job"
    job_path = f"/budget-window-jobs/{job_id}" if budget_window else f"/jobs/{job_id}"
    received = []
    worker_app = "test-worker"
    typed_error = YEAR_ERROR
    if isinstance(failure, str):
        typed_error = {
            "code": "SPM_CONFIGURATION_UNAVAILABLE",
            "message": "Worker SPM receipt does not cover requested year",
        }
        side = failure.removeprefix("segmented-")
        worker_result = (
            {
                "kind": "budgetWindow",
                "windowSize": 2,
                "annualImpacts": [
                    segmented_result("2035"),
                    segmented_result("2036", side),
                ],
            }
            if budget_window
            else segmented_result("2036", side)
        )

    def transport(request):
        received.append((request.method, request.url.path))
        if request.method == "POST" and worker_app == "replacement-worker":
            expected_path = (
                "/simulate/economy/budget-window"
                if budget_window
                else "/simulate/economy/comparison"
            )
            assert request.url.path == expected_path
            return httpx.Response(
                200,
                json={
                    "job_id": "replacement-job",
                    "batch_job_id": "replacement-job",
                    "status": "submitted",
                    "resolved_app_name": worker_app,
                },
            )
        assert request.method == "GET", "Polling must not submit a replacement job"
        if request.url.path == "/versions":
            return httpx.Response(
                200,
                json={
                    "policyengine": {"5.3.1": worker_app},
                    "spm_capabilities": {
                        "5.3.1": {
                            "contract_version": "canonical-spm-v1",
                            "defaults": SELECTION,
                        }
                    },
                },
            )
        if request.url.path == "/versions/policyengine":
            return httpx.Response(200, json={"5.3.1": worker_app})
        assert request.url.path == job_path
        if received.count(("GET", job_path)) > 1:
            return httpx.Response(404, json={"detail": "Job expired"})
        if isinstance(failure, str):
            return httpx.Response(
                200, json={"status": "complete", "result": worker_result}
            )
        return httpx.Response(
            failure,
            json={"status": "error", "errors": [typed_error]},
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
            service._resolve_runtime_bundle_for_setup_options(setup)
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
                "message": typed_error["message"],
                "errors": [typed_error],
            }
            if budget_window:
                assert window_cache.get_completed_result(cache_key) is None
                assert window_cache.get_batch_job_id(cache_key) is None
                assert window_cache.get_terminal_error(cache_key) == typed_error
            else:
                stored = annual_cache.get_by_execution_id(job_id)
                assert stored.status == "error"
                assert stored.reform_impact_json == {}
                assert stored.error_code == typed_error["code"]
                assert stored.message == typed_error["message"]
                assert stored.execution_id is None
                assert stored.end_time is not None
                assert stored.options_hash == setup.options_hash
                assert stored.options_json == setup.options

            # The worker job vanishes after its first failure. Recreate both
            # services and cache facades to prove replay uses shared storage.
            annual_cache = ReformImpactCache(backend, namespace)
            annual_impacts = ReformImpactsService(annual_cache)
            window_cache = BudgetWindowCache(backend, namespace)
            service = EconomyService(
                reform_impacts_service_=annual_impacts,
                budget_window_cache_=window_cache,
                simulation_entrypoint_=gateway,
            )
            monkeypatch.setattr(economy_routes, "economy_service", service)

        # Only a newly resolved worker permits a replacement submission.
        worker_app = "replacement-worker"
        monkeypatch.setattr(service, "_get_policy_jsons", lambda *_: ({}, {}))
        response = app.test_client().get(
            url,
            query_string={"region": "us", "version": "1.0.0", **query},
        )
        assert response.status_code == 200, response.json
        assert response.json["status"] == "computing"
        if budget_window:
            assert window_cache.get_terminal_error(cache_key) == typed_error
            assert received.count(("POST", "/simulate/economy/budget-window")) == 1
        else:
            replacement = annual_cache.get_by_execution_id("replacement-job")
            assert replacement.options_hash != setup.options_hash
            assert replacement.options_json == setup.options
            assert annual_cache.get_by_execution_id(job_id).status == "error"
            assert received.count(("POST", "/simulate/economy/comparison")) == 1

    assert received.count(("GET", job_path)) == 1


@pytest.mark.parametrize("budget_window", [False, True], ids=["annual", "window"])
def test_an_uncertifiable_stored_result_becomes_terminal_instead_of_repeating(
    monkeypatch, budget_window
):
    """A stored success this build cannot certify needs somewhere to end.

    Both stores already replay a recorded typed failure before they read their
    success payload. Without recording one, the same uncertifiable payload is
    re-validated on every poll: a 400 the caller can never move past and a
    worker handle that is never released.
    """
    monkeypatch.setattr(worker_spm, "normalize_spm_selection", lambda *_: SELECTION)
    monkeypatch.setattr(economy_module, "COUNTRY_PACKAGE_VERSIONS", {"us": "1.0.0"})
    monkeypatch.setattr(economy_module, "POLICYENGINE_VERSION", "5.3.1")
    job_id = "uncertifiable-stored-result"
    received = []

    def transport(request):
        received.append((request.method, request.url.path))
        assert request.method == "GET", "A stored result must not submit a job"
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
        raise AssertionError(f"Unexpected worker call: {request.url.path}")

    gateway = object.__new__(SimulationEntrypointClient)
    gateway.base_url = "https://worker.invalid"
    backend = InMemoryCacheBackend()
    namespace = CacheNamespace("test", "uncertifiable-stored-result")
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

    # A stored payload whose reform receipt covers the wrong year: a success
    # this build cannot certify, exactly as a worker defect would leave it.
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
            service._resolve_runtime_bundle_for_setup_options(setup)
            cache_key = service._build_budget_window_cache_key(setup)
            window_cache.set_completed_result(
                cache_key,
                {
                    "kind": "budgetWindow",
                    "windowSize": 2,
                    "annualImpacts": [
                        segmented_result("2035"),
                        segmented_result("2036", "reform"),
                    ],
                },
            )
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
                status="ok",
                api_version=setup.api_version,
                reform_impact_json=segmented_result("2036", "reform"),
                start_time=None,
                execution_id=job_id,
            )
            url = "/us/economy/1/over/2"
            query = {"time_period": "2036"}

        first = None
        for _ in range(2):
            response = app.test_client().get(
                url,
                query_string={"region": "us", "version": "1.0.0", **query},
            )
            assert response.status_code == 400, response.json
            assert response.json["errors"][0]["code"] == "SPM_CONFIGURATION_UNAVAILABLE"
            if first is None:
                first = response.json
            assert response.json == first

            if budget_window:
                terminal = window_cache.get_terminal_error(cache_key)
                assert terminal["code"] == "SPM_CONFIGURATION_UNAVAILABLE"
            else:
                stored = annual_cache.get_by_execution_id(job_id)
                assert stored.status == "error"
                assert stored.error_code == "SPM_CONFIGURATION_UNAVAILABLE"
                assert stored.execution_id is None
                assert stored.options_hash == setup.options_hash

            # Replay must come from storage, not from re-reading the payload.
            annual_cache = ReformImpactCache(backend, namespace)
            annual_impacts = ReformImpactsService(annual_cache)
            window_cache = BudgetWindowCache(backend, namespace)
            service = EconomyService(
                reform_impacts_service_=annual_impacts,
                budget_window_cache_=window_cache,
                simulation_entrypoint_=gateway,
            )
            monkeypatch.setattr(economy_routes, "economy_service", service)
