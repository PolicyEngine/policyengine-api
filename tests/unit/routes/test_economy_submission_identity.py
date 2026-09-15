"""Cache identity must describe the worker execution actually being qualified."""

from types import SimpleNamespace
import json
from uuid import uuid4

from flask import Flask
import httpx
import pytest

from policyengine_api.libs.simulation_entrypoint import SimulationEntrypointClient
from policyengine_api.routes import economy_routes
from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.reform_impacts import (
    REFORM_IMPACT_INDEX_LIMIT,
    ReformImpactCache,
)
from policyengine_api.services import economy_service as economy_module
from policyengine_api.services.budget_window_cache import BudgetWindowCache
from policyengine_api.services.economy_service import EconomyService
from policyengine_api.services.reform_impacts_service import ReformImpactsService
from tests.integration.test_cloud_run_candidate import (
    test_cloud_run_candidate_current_law_economy as run_smoke,
)


@pytest.fixture
def economy(monkeypatch):
    # The transport/cache boundary needs no real bundle or population compute.
    monkeypatch.setattr(economy_module, "validate_worker_spm", lambda *a, **k: None)
    monkeypatch.setattr(economy_module, "COUNTRY_PACKAGE_VERSIONS", {"us": "1.0.0"})
    monkeypatch.setattr(economy_routes, "COUNTRY_PACKAGE_VERSIONS", {"us": "1.0.0"})
    monkeypatch.setattr(economy_module, "POLICYENGINE_VERSION", "5.2.0")
    backend = InMemoryCacheBackend()
    namespace = CacheNamespace("test", "submission-identity")
    impacts = ReformImpactsService(ReformImpactCache(backend, namespace))
    window = BudgetWindowCache(backend, namespace)
    gateway = object.__new__(SimulationEntrypointClient)
    gateway.base_url = "https://worker.invalid"
    service = EconomyService(
        reform_impacts_service_=impacts,
        budget_window_cache_=window,
        simulation_entrypoint_=gateway,
    )
    monkeypatch.setattr(service, "_get_policy_jsons", lambda *_: ({}, {}))
    monkeypatch.setattr(economy_routes, "economy_service", service)
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(economy_routes.economy_bp)
    return service, impacts, window, gateway, app.test_client()


BUDGET_WINDOW_QUERY = {"region": "us", "start_year": "2025", "window_size": "2"}


def _budget_window_keys(service):
    """Return the budget-window cache keys for worker A and worker B."""

    keys = {}
    for app_name in ("worker-A", "worker-B"):
        setup = service._build_economic_impact_setup_options(
            country_id="us",
            policy_id=2,
            baseline_policy_id=2,
            region="us",
            dataset="default",
            time_period="budget_window:2025:2",
            options={},
            api_version="1.0.0",
        )
        setup.runtime_app_name = app_name
        setup.options_hash = service._build_options_hash(
            options=setup.options,
            model_version=setup.model_version,
            dataset=setup.dataset,
            data_version=setup.data_version,
            policyengine_version=setup.policyengine_version,
            runtime_app_name=app_name,
            target=setup.target,
        )
        keys[app_name] = service._build_budget_window_cache_key(setup)
    return keys


@pytest.mark.parametrize("submitted_app", ["worker-B", None, ""])
def test_budget_submission_identity_is_verified_before_caching(economy, submitted_app):
    service, _, window, gateway, client = economy
    active_app = "worker-A"
    posts = []

    def transport(request):
        nonlocal active_app
        if request.url.path == "/versions/policyengine":
            return httpx.Response(200, json={"5.2.0": active_app})
        assert request.method == "POST"
        assert request.url.path == "/simulate/economy/budget-window"
        posts.append(request)
        # The registry changes after A was resolved, before B was submitted.
        active_app = "worker-B"
        return httpx.Response(
            200,
            json={
                "batch_job_id": "batch-B",
                "status": "submitted",
                "resolved_app_name": submitted_app,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(transport)) as gateway.client:
        keys = _budget_window_keys(service)
        key_a = keys["worker-A"]
        for attempt in range(2):
            # A rollback must never replay B's handle under A's cache identity.
            active_app = "worker-A"
            response = client.get(
                "/us/economy/2/over/2/budget-window",
                query_string=BUDGET_WINDOW_QUERY,
            )
            if attempt == 0:
                # The request that saw the mismatch says "come back shortly",
                # not "you sent a bad request" and not "something broke".
                assert response.status_code == 503, response.json
                assert response.headers["Retry-After"] == "5"
                assert "registry changed" in response.json["message"]
            else:
                # A's starting claim still stands, so the retry waits rather
                # than paying for a second batch.
                assert response.status_code == 200, response.json
                assert response.json["status"] == "computing"
            assert window.get_batch_job_id(key_a) is None
            assert window.get_completed_result(key_a) is None
            assert window.get_terminal_error(key_a) is None
        # One POST, one spawned batch: the retry never reached the gateway.
        assert len(posts) == 1


def test_budget_submission_identity_mismatch_retains_the_batch_for_the_next_poll(
    economy,
):
    service, _, window, gateway, client = economy
    active_app = "worker-A"
    posts = []

    def transport(request):
        nonlocal active_app
        if request.url.path == "/versions/policyengine":
            return httpx.Response(200, json={"5.2.0": active_app})
        if request.method == "POST":
            posts.append(request)
            # The rollout completes between this request's lookup and its POST.
            active_app = "worker-B"
            return httpx.Response(
                200,
                json={
                    "batch_job_id": "batch-B",
                    "status": "submitted",
                    "resolved_app_name": "worker-B",
                },
            )
        assert request.url.path == "/budget-window-jobs/batch-B"
        return httpx.Response(
            200,
            json={
                "batch_job_id": "batch-B",
                "status": "running",
                "progress": 0,
                "completed_years": [],
                "running_years": ["2025"],
                "queued_years": ["2026"],
                "failed_years": [],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(transport)) as gateway.client:
        keys = _budget_window_keys(service)
        response = client.get(
            "/us/economy/2/over/2/budget-window",
            query_string=BUDGET_WINDOW_QUERY,
        )
        assert response.status_code == 503, response.json
        # The spawned batch is filed under the worker that actually ran it,
        # never under the identity this request resolved.
        assert window.get_batch_job_id(keys["worker-A"]) is None
        assert window.get_batch_job_id(keys["worker-B"]) == "batch-B"

        # The next poll re-reads the registry, which now serves worker B, and
        # adopts the running batch instead of spawning a second one.
        response = client.get(
            "/us/economy/2/over/2/budget-window",
            query_string=BUDGET_WINDOW_QUERY,
        )
        assert response.status_code == 200, response.json
        assert response.json["status"] == "computing"
        assert response.headers["X-PolicyEngine-Budget-Window-Cache"] == "batch-id-hit"
        assert len(posts) == 1


def test_budget_submission_identity_mismatch_never_overwrites_another_claim(economy):
    service, _, window, gateway, client = economy
    active_app = "worker-A"

    def transport(request):
        if request.url.path == "/versions/policyengine":
            return httpx.Response(200, json={"5.2.0": active_app})
        return httpx.Response(
            200,
            json={
                "batch_job_id": "batch-late",
                "status": "submitted",
                "resolved_app_name": "worker-B",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(transport)) as gateway.client:
        keys = _budget_window_keys(service)
        window.store_batch_job_id(keys["worker-B"], "batch-already-running")
        response = client.get(
            "/us/economy/2/over/2/budget-window",
            query_string=BUDGET_WINDOW_QUERY,
        )
        assert response.status_code == 503, response.json
        # Worker B's key already points at a batch; displacing it would orphan
        # that one instead.
        assert window.get_batch_job_id(keys["worker-B"]) == "batch-already-running"


@pytest.mark.parametrize(
    "path,query",
    [
        ("/us/economy/2/over/2", {"region": "ut", "time_period": "2025"}),
        ("/us/economy/2/over/2/budget-window", BUDGET_WINDOW_QUERY),
    ],
)
def test_missing_registry_entry_is_a_dependency_failure_not_a_bad_request(
    economy, path, query
):
    _, _, _, gateway, client = economy

    def transport(request):
        assert request.url.path == "/versions/policyengine"
        # The registry is reachable but publishes no worker for this bundle.
        return httpx.Response(200, json={"4.0.0": "worker-old"})

    with httpx.Client(transport=httpx.MockTransport(transport)) as gateway.client:
        response = client.get(path, query_string=query)
        assert response.status_code == 503, response.json
        assert response.headers["Retry-After"] == "30"
        assert (
            "No simulation worker is currently registered" in response.json["message"]
        )


@pytest.mark.parametrize(
    "path,query",
    [
        ("/us/economy/2/over/2", {"region": "ut", "time_period": "2025"}),
        ("/us/economy/2/over/2/budget-window", BUDGET_WINDOW_QUERY),
    ],
)
def test_unreachable_registry_is_a_dependency_failure_not_a_server_fault(
    economy, path, query
):
    _, _, _, gateway, client = economy

    def transport(request):
        raise httpx.ConnectError("registry unreachable", request=request)

    with httpx.Client(transport=httpx.MockTransport(transport)) as gateway.client:
        response = client.get(path, query_string=query)
        # 500 is a status polling clients retry immediately; 503 carries an
        # explicit back-off for the same condition.
        assert response.status_code == 503, response.json
        assert response.headers["Retry-After"] == "30"
        assert "registry is unavailable" in response.json["message"]


def test_invalid_query_is_still_a_bad_request_when_the_registry_is_empty(economy):
    _, _, _, gateway, client = economy

    def transport(request):
        return httpx.Response(200, json={})

    with httpx.Client(transport=httpx.MockTransport(transport)) as gateway.client:
        response = client.get(
            "/us/economy/2/over/2/budget-window",
            query_string={"region": "us", "start_year": "2025", "window_size": "0"},
        )
        assert response.status_code == 400, response.json


def test_nonce_floods_cannot_evict_the_shared_scope_entry(economy):
    service, impacts, _, gateway, client = economy
    posts = []
    shared_result = {"budget": {"budgetary_impact": 0}, "resolved_app_name": "worker-A"}

    def transport(request):
        if request.url.path == "/versions/policyengine":
            return httpx.Response(200, json={"5.2.0": "worker-A"})
        posts.append(request)
        return httpx.Response(
            200,
            json={
                "job_id": f"job-{len(posts)}",
                "status": "submitted",
                "resolved_app_name": "worker-A",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(transport)) as gateway.client:
        shared = service._build_economic_impact_setup_options(
            country_id="us",
            policy_id=2,
            baseline_policy_id=2,
            region="state/ut",
            dataset="default",
            time_period="2025",
            options={},
            api_version="1.0.0",
        )
        service._resolve_runtime_bundle_for_setup_options(shared)
        impacts.set_reform_impact(
            country_id=shared.country_id,
            policy_id=2,
            baseline_policy_id=2,
            region=shared.region,
            dataset=shared.dataset,
            time_period=shared.time_period,
            options=shared.options,
            options_hash=shared.options_hash,
            status="ok",
            api_version=shared.api_version,
            reform_impact_json=shared_result,
            start_time=None,
            execution_id="shared-job",
        )

        # One more than the shared scope index holds. Every one of these is
        # newer than the shared entry, so an unpartitioned index would have
        # trimmed the shared entry out of its own scope.
        for index in range(REFORM_IMPACT_INDEX_LIMIT + 1):
            nonce = str(uuid4())
            isolated = service._build_economic_impact_setup_options(
                country_id="us",
                policy_id=2,
                baseline_policy_id=2,
                region="state/ut",
                dataset="default",
                time_period="2025",
                options={"cache_nonce": nonce},
                api_version="1.0.0",
            )
            service._resolve_runtime_bundle_for_setup_options(isolated)
            impacts.set_reform_impact(
                country_id=isolated.country_id,
                policy_id=2,
                baseline_policy_id=2,
                region=isolated.region,
                dataset=isolated.dataset,
                time_period=isolated.time_period,
                options=isolated.options,
                options_hash=isolated.options_hash,
                status="ok",
                api_version=isolated.api_version,
                reform_impact_json={"budget": {"budgetary_impact": 0}},
                start_time=None,
                execution_id=f"isolated-job-{index}",
            )

        response = client.get(
            "/us/economy/2/over/2", query_string={"region": "ut", "time_period": "2025"}
        )
        assert response.status_code == 200, response.json
        assert response.json["status"] == "ok"
        # The shared entry answered; nothing was resubmitted to the worker.
        assert not posts


def test_candidate_smoke_cannot_pass_from_prior_result_when_submission_is_broken(
    economy,
):
    service, impacts, _, gateway, client = economy
    posts = []
    result = {"budget": {"budgetary_impact": 0}, "resolved_app_name": "worker-A"}
    metadata = {
        "current_law_id": 2,
        "economy_options": {"time_period": [{"name": "2025"}]},
        "spm": {"available": False},
    }

    def transport(request):
        if request.url.path == "/versions/policyengine":
            return httpx.Response(200, json={"5.2.0": "worker-A"})
        assert request.method == "POST"
        assert request.url.path == "/simulate/economy/comparison"
        posts.append(request)
        raise httpx.ConnectError("candidate submission is broken", request=request)

    with httpx.Client(transport=httpx.MockTransport(transport)) as gateway.client:
        setup = service._build_economic_impact_setup_options(
            country_id="us",
            policy_id=2,
            baseline_policy_id=2,
            region="state/ut",
            dataset="default",
            time_period="2025",
            options={},
            api_version="1.0.0",
        )
        service._resolve_runtime_bundle_for_setup_options(setup)
        impacts.set_reform_impact(
            country_id=setup.country_id,
            policy_id=2,
            baseline_policy_id=2,
            region=setup.region,
            dataset=setup.dataset,
            time_period=setup.time_period,
            options=setup.options,
            options_hash=setup.options_hash,
            status="ok",
            api_version=setup.api_version,
            reform_impact_json=result,
            start_time=None,
            execution_id="prior-deployment-job",
        )
        response = client.get(
            "/us/economy/2/over/2", query_string={"region": "ut", "time_period": "2025"}
        )
        assert response.json["status"] == "ok"
        assert not posts

        metadata_client = SimpleNamespace(
            get=lambda _: SimpleNamespace(
                raise_for_status=lambda: None, json=lambda: {"result": metadata}
            )
        )

        def poll(_client, path, query, **kwargs):
            response = client.get(path, query_string=query)
            assert response.status_code == 200, response.json
            return response.json

        with pytest.raises(httpx.ConnectError, match="candidate submission is broken"):
            run_smoke(metadata_client, poll)
        assert len(posts) == 1
        assert "cache_nonce" not in json.loads(posts[0].content)


def test_nonce_polling_reuses_its_job_but_another_nonce_submits_again(economy):
    _, _, _, gateway, client = economy
    submissions = []

    def transport(request):
        if request.url.path == "/versions/policyengine":
            return httpx.Response(200, json={"5.2.0": "worker-A"})
        if request.method == "POST":
            submissions.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "job_id": f"job-{len(submissions)}",
                    "status": "submitted",
                    "resolved_app_name": "worker-A",
                },
            )
        assert request.url.path == "/jobs/job-1"
        return httpx.Response(
            200,
            json={
                "status": "complete",
                "result": {"budget": {"budgetary_impact": 0}},
                "resolved_app_name": "worker-A",
            },
        )

    path = "/us/economy/2/over/2"
    query = {"region": "ut", "time_period": "2025", "cache_nonce": str(uuid4())}
    with httpx.Client(transport=httpx.MockTransport(transport)) as gateway.client:
        for expected in ("computing", "ok", "ok"):
            response = client.get(path, query_string=query)
            assert response.status_code == 200, response.json
            assert response.json["status"] == expected
        assert len(submissions) == 1
        query["cache_nonce"] = str(uuid4())
        response = client.get(path, query_string=query)
        assert response.json["status"] == "computing"
        assert len(submissions) == 2
        # Job/correlation metadata varies; the worker's calculation is identical.
        computation_payloads = [
            {key: value for key, value in payload.items() if not key.startswith("_")}
            for payload in submissions
        ]
        assert computation_payloads[0] == computation_payloads[1]
        assert "cache_nonce" not in submissions[0]


@pytest.mark.parametrize(
    "nonce_values", [["invalid"], [""], [str(uuid4()), str(uuid4())]]
)
def test_invalid_or_duplicate_nonce_never_reaches_the_worker(economy, nonce_values):
    _, _, _, _, client = economy
    response = client.get(
        "/us/economy/2/over/2",
        query_string=[("region", "ut"), ("time_period", "2025")]
        + [("cache_nonce", value) for value in nonce_values],
    )
    assert response.status_code == 400, response.json
