"""Typed worker failures become durable terminal HTTP polling responses."""

from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from flask import Flask

from policyengine_api import worker_spm
from policyengine_api.libs.simulation_entrypoint import SimulationEntrypointClient
from policyengine_api.routes import economy_routes
from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.reform_impacts import ReformImpactCache
from policyengine_api.services import economy_service as economy_module
from policyengine_api.services.budget_window_cache import BudgetWindowCache
from policyengine_api.services.economic_impact_request import EconomicImpactRequest
from policyengine_api.services.economy_impact_types import ImpactPolicies
from policyengine_api.services.economy_service import EconomyService
from policyengine_api.services.reform_impacts_service import (
    ReformImpactExecution,
    ReformImpactsService,
)

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
DATASET_YEAR_ERROR = {
    "code": "DATASET_YEAR_UNAVAILABLE",
    "message": (
        "US results are available for 2024 to 2035. 2036 is outside the years "
        "the current US model and data cover."
    ),
}


def segmented_result(year, invalid_side=None):
    receipt = {
        "schema_version": "canonical-spm-provenance-v2",
        "forecast_id": "test-only",
        "forecast_sha256": SELECTION["forecast_content_sha256"],
        "scenario": SELECTION["scenario"],
        "geography_kind": SELECTION["geography_kind"],
        "geography_id": None,
        "county_vintage": "2020",
        "as_of": None,
        "runtime_versions": {
            "policyengine": "test",
            "policyengine-core": "test",
            "policyengine-us": "test",
            "spm-calculator": "test",
        },
        "years": [year],
    }
    result = {
        "year": year,
        "spm_provenance": {
            "schema_version": "canonical-spm-comparison-v2",
            "baseline": {"receipt": dict(receipt), "execution_count": 2},
            "reform": {"receipt": dict(receipt), "execution_count": 2},
        },
    }
    if invalid_side:
        result["spm_provenance"][invalid_side]["receipt"]["years"] = ["2000"]
    return result


def _versions_response(path: str, worker_app: str) -> httpx.Response | None:
    """Answer the worker's version discovery routes, or return None."""
    if path == "/versions":
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
    if path == "/versions/policyengine":
        return httpx.Response(200, json={"5.3.1": worker_app})
    return None


class _FailingJobWorker:
    """A worker HTTP API whose job fails once with a typed error, then expires."""

    def __init__(
        self,
        *,
        job_path: str,
        failure: int | str,
        typed_error: dict[str, str],
        worker_result: dict[str, Any] | None,
    ) -> None:
        self.job_path = job_path
        self.failure = failure
        self.typed_error = typed_error
        self.worker_result = worker_result
        self.app_name = "test-worker"
        self.received: list[tuple[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.received.append((request.method, request.url.path))
        if request.method == "POST" and self.app_name == "replacement-worker":
            assert request.url.path == "/simulate/economy/comparison"
            return httpx.Response(
                200, json={"job_id": "replacement-job", "status": "submitted"}
            )
        assert request.method == "GET", "Polling must not submit a replacement job"
        versions = _versions_response(request.url.path, self.app_name)
        if versions is not None:
            return versions
        assert request.url.path == self.job_path
        if self.received.count(("GET", self.job_path)) > 1:
            return httpx.Response(404, json={"detail": "Job expired"})
        if isinstance(self.failure, str):
            return httpx.Response(
                200, json={"status": "complete", "result": self.worker_result}
            )
        return httpx.Response(
            self.failure,
            json={"status": "error", "errors": [self.typed_error]},
        )


def _versions_only_worker(request: httpx.Request) -> httpx.Response:
    """Answer as a worker HTTP API that serves only version discovery."""
    assert request.method == "GET", "A stored result must not submit a job"
    versions = _versions_response(request.url.path, "test-worker")
    if versions is not None:
        return versions
    msg = f"Unexpected worker call: {request.url.path}"
    raise AssertionError(msg)


def _typed_failure(
    failure: int | str, *, budget_window: bool
) -> tuple[dict[str, str], dict[str, Any] | None]:
    """Return the typed error the routes must report, and the worker's result."""
    if not isinstance(failure, str):
        return YEAR_ERROR, None
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
    typed_error = {
        "code": "SPM_CONFIGURATION_UNAVAILABLE",
        "message": "baseline and reform SPM receipts differ",
    }
    return typed_error, worker_result


def _patch_spm_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_spm, "normalize_spm_selection", lambda *_: SELECTION)
    monkeypatch.setattr(economy_module, "COUNTRY_PACKAGE_VERSIONS", {"us": "1.0.0"})
    monkeypatch.setattr(economy_module, "POLICYENGINE_VERSION", "5.3.1")


def _worker_gateway() -> SimulationEntrypointClient:
    gateway = object.__new__(SimulationEntrypointClient)
    gateway.base_url = "https://worker.invalid"
    return gateway


@dataclass
class _EconomyStack:
    """The caches and service one process builds over the shared storage."""

    annual_cache: ReformImpactCache
    annual_impacts: ReformImpactsService
    window_cache: BudgetWindowCache
    service: EconomyService


def _install_economy_stack(
    monkeypatch: pytest.MonkeyPatch,
    gateway: SimulationEntrypointClient,
    backend: Any,
    namespace: CacheNamespace,
) -> _EconomyStack:
    """Build fresh cache facades and a service over ``backend`` and route to it."""
    annual_cache = ReformImpactCache(backend, namespace)
    annual_impacts = ReformImpactsService(annual_cache)
    window_cache = BudgetWindowCache(backend, namespace)
    service = EconomyService(
        reform_impacts_service_=annual_impacts,
        budget_window_cache_=window_cache,
        simulation_entrypoint_=gateway,
    )
    monkeypatch.setattr(economy_routes, "economy_service", service)
    return _EconomyStack(annual_cache, annual_impacts, window_cache, service)


def _economy_app() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(economy_routes.economy_bp)
    return app


def _setup_options(service: EconomyService, *, budget_window: bool) -> Any:
    return service._build_economic_impact_setup_options(
        EconomicImpactRequest(
            country_id="us",
            policy_id=1,
            baseline_policy_id=2,
            region="us",
            dataset="default",
            options={},
            api_version="1.0.0",
        ),
        time_period="budget_window:2035:2" if budget_window else "2036",
    )


def _store_annual_impact(
    stack: Any,
    setup: Any,
    *,
    status: str,
    reform_impact_json: dict[str, Any],
    execution_id: str,
) -> None:
    stack.service._resolve_runtime_bundle_for_setup_options(setup)
    stack.annual_impacts.set_reform_impact(
        stack.service._reform_impact_identity(setup),
        ReformImpactExecution(execution_id=execution_id, start_time=None),
        options=setup.options,
        status=status,
        reform_impact_json=reform_impact_json,
    )


def _economy_request(*, budget_window: bool) -> tuple[str, dict[str, str]]:
    """Return the economy route and query for an annual or budget-window run."""
    if budget_window:
        return "/us/economy/1/over/2/budget-window", {
            "start_year": "2035",
            "window_size": "2",
        }
    return "/us/economy/1/over/2", {"time_period": "2036"}


def _get_economy(app: Flask, url: str, query: dict[str, str]) -> Any:
    return app.test_client().get(
        url,
        query_string={"region": "us", "version": "1.0.0", **query},
    )


def _assert_window_failure_recorded(
    state: Any, typed_error: dict[str, str], setup: Any
) -> None:
    assert state is not None
    assert state.status == "failed"
    assert state.failure_type == "spm_validation"
    assert state.error == typed_error
    assert state.observability_id == setup.observability_id


def _assert_annual_failure_recorded(
    stored: Any, typed_error: dict[str, str], setup: Any
) -> None:
    assert stored.status == "error"
    assert stored.reform_impact_json == {}
    assert stored.error_code == typed_error["code"]
    assert stored.message == typed_error["message"]
    assert stored.execution_id is None
    assert stored.end_time is not None
    assert stored.options_hash == setup.options_hash
    assert stored.options_json == setup.options


@pytest.mark.parametrize(
    "failure", [400, 422, "segmented-baseline", "segmented-reform"]
)
@pytest.mark.parametrize("budget_window", [False, True], ids=["annual", "window"])
def test_typed_worker_error_is_terminal_and_replays_after_service_recreation(
    monkeypatch, failure, budget_window
):
    # Certification is synthetic; the HTTP consumer, routes and both caches are
    # real. No worker execution or dataset loading is needed for this boundary.
    _patch_spm_release(monkeypatch)
    job_id = "unsupported-year-job"
    job_path = f"/budget-window-jobs/{job_id}" if budget_window else f"/jobs/{job_id}"
    typed_error, worker_result = _typed_failure(failure, budget_window=budget_window)
    worker = _FailingJobWorker(
        job_path=job_path,
        failure=failure,
        typed_error=typed_error,
        worker_result=worker_result,
    )

    gateway = _worker_gateway()
    backend = InMemoryCacheBackend()
    namespace = CacheNamespace("test", "typed-year-worker-polling")
    stack = _install_economy_stack(monkeypatch, gateway, backend, namespace)
    app = _economy_app()

    with httpx.Client(transport=httpx.MockTransport(worker)) as gateway.client:
        setup = _setup_options(stack.service, budget_window=budget_window)
        if budget_window:
            cache_key = stack.service._build_budget_window_cache_key(setup)
            stack.window_cache.store_submitted(
                cache_key,
                job_id,
                setup.observability_id,
            )
        else:
            _store_annual_impact(
                stack,
                setup,
                status="computing",
                reform_impact_json={},
                execution_id=job_id,
            )
        url, query = _economy_request(budget_window=budget_window)

        worker.received.clear()
        for _ in range(2):
            response = _get_economy(app, url, query)
            assert response.status_code == 400, response.json
            assert response.json == {
                "status": "error",
                "result": None,
                "message": typed_error["message"],
                "errors": [typed_error],
            }
            if budget_window:
                _assert_window_failure_recorded(
                    stack.window_cache.get_state(cache_key), typed_error, setup
                )
            else:
                _assert_annual_failure_recorded(
                    stack.annual_cache.get_by_execution_id(job_id), typed_error, setup
                )

            # The worker job vanishes after its first failure. Recreate both
            # services and cache facades to prove replay uses shared storage.
            stack = _install_economy_stack(monkeypatch, gateway, backend, namespace)

        if not budget_window:
            # Preserve the existing retry policy: only a newly resolved worker
            # creates a fresh canonical cache identity and permits submission.
            worker.app_name = "replacement-worker"
            monkeypatch.setattr(
                stack.service,
                "_get_policy_jsons",
                lambda *_: ImpactPolicies(baseline={}, reform={}),
            )
            response = _get_economy(app, url, query)
            assert response.status_code == 200, response.json
            assert response.json["status"] == "computing"
            replacement = stack.annual_cache.get_by_execution_id("replacement-job")
            assert replacement.options_hash != setup.options_hash
            assert replacement.options_json == setup.options
            assert stack.annual_cache.get_by_execution_id(job_id).status == "error"
            assert worker.received.count(("POST", "/simulate/economy/comparison")) == 1

    assert worker.received.count(("GET", job_path)) == 1


@pytest.mark.parametrize("budget_window", [False, True], ids=["annual", "window"])
def test_a_dataset_year_error_returns_400_and_replays_from_storage(
    monkeypatch, budget_window
):
    """A year the worker's model cannot project is a caller error, not a 502.

    The simulation service answers the poll with 400 and the stable code
    DATASET_YEAR_UNAVAILABLE. The route returns that code and its readable
    message, and later polls replay the stored typed failure without asking
    the worker again.
    """
    _patch_spm_release(monkeypatch)
    job_id = "dataset-year-job"
    job_path = f"/budget-window-jobs/{job_id}" if budget_window else f"/jobs/{job_id}"
    worker = _FailingJobWorker(
        job_path=job_path,
        failure=400,
        typed_error=DATASET_YEAR_ERROR,
        worker_result=None,
    )

    gateway = _worker_gateway()
    backend = InMemoryCacheBackend()
    namespace = CacheNamespace("test", "dataset-year-worker-polling")
    stack = _install_economy_stack(monkeypatch, gateway, backend, namespace)
    app = _economy_app()

    with httpx.Client(transport=httpx.MockTransport(worker)) as gateway.client:
        setup = _setup_options(stack.service, budget_window=budget_window)
        if budget_window:
            cache_key = stack.service._build_budget_window_cache_key(setup)
            stack.window_cache.store_submitted(
                cache_key,
                job_id,
                setup.observability_id,
            )
        else:
            _store_annual_impact(
                stack,
                setup,
                status="computing",
                reform_impact_json={},
                execution_id=job_id,
            )
        url, query = _economy_request(budget_window=budget_window)

        worker.received.clear()
        for _ in range(2):
            response = _get_economy(app, url, query)
            assert response.status_code == 400, response.json
            assert response.json == {
                "status": "error",
                "result": None,
                "message": DATASET_YEAR_ERROR["message"],
                "errors": [DATASET_YEAR_ERROR],
            }
            if budget_window:
                _assert_window_failure_recorded(
                    stack.window_cache.get_state(cache_key), DATASET_YEAR_ERROR, setup
                )
            else:
                _assert_annual_failure_recorded(
                    stack.annual_cache.get_by_execution_id(job_id),
                    DATASET_YEAR_ERROR,
                    setup,
                )
            stack = _install_economy_stack(monkeypatch, gateway, backend, namespace)

    assert worker.received.count(("GET", job_path)) == 1


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
    _patch_spm_release(monkeypatch)
    job_id = "uncertifiable-stored-result"

    gateway = _worker_gateway()
    backend = InMemoryCacheBackend()
    namespace = CacheNamespace("test", "uncertifiable-stored-result")
    stack = _install_economy_stack(monkeypatch, gateway, backend, namespace)
    app = _economy_app()

    # A stored payload whose reform receipt covers the wrong year: a success
    # this build cannot certify, exactly as a worker defect would leave it.
    transport = httpx.MockTransport(_versions_only_worker)
    with httpx.Client(transport=transport) as gateway.client:
        setup = _setup_options(stack.service, budget_window=budget_window)
        if budget_window:
            cache_key = stack.service._build_budget_window_cache_key(setup)
            stack.window_cache.set_completed_result(
                cache_key,
                {
                    "kind": "budgetWindow",
                    "windowSize": 2,
                    "annualImpacts": [
                        segmented_result("2035"),
                        segmented_result("2036", "reform"),
                    ],
                },
                setup.observability_id,
            )
        else:
            _store_annual_impact(
                stack,
                setup,
                status="ok",
                reform_impact_json=segmented_result("2036", "reform"),
                execution_id=job_id,
            )
        url, query = _economy_request(budget_window=budget_window)

        first = None
        for _ in range(2):
            response = _get_economy(app, url, query)
            assert response.status_code == 400, response.json
            assert response.json["errors"][0]["code"] == "SPM_CONFIGURATION_UNAVAILABLE"
            if first is None:
                first = response.json
            assert response.json == first

            if budget_window:
                state = stack.window_cache.get_state(cache_key)
                assert state is not None
                assert state.status == "failed"
                assert state.failure_type == "spm_validation"
                assert state.error is not None
                assert state.error["code"] == "SPM_CONFIGURATION_UNAVAILABLE"
            else:
                stored = stack.annual_cache.get_by_execution_id(job_id)
                assert stored.status == "error"
                assert stored.error_code == "SPM_CONFIGURATION_UNAVAILABLE"
                assert stored.execution_id is None
                assert stored.options_hash == setup.options_hash

            # Replay must come from storage, not from re-reading the payload.
            stack = _install_economy_stack(monkeypatch, gateway, backend, namespace)
