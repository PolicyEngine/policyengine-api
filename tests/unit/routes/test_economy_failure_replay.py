"""Annual worker failures retain their status when subsequent HTTP polls replay them."""

from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask
import pytest

from policyengine_api.routes import economy_routes
from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.reform_impacts import ReformImpactCache
from policyengine_api.services import economy_service as economy_module
from policyengine_api.services.economy_service import EconomyService
from policyengine_api.services.reform_impacts_service import ReformImpactsService
from policyengine_api import worker_spm


SELECTION = {
    "forecast_content_sha256": "a" * 64,
    "scenario": "baseline",
    "geography_kind": "national",
    "geography_id": None,
    "county_vintage": "2020",
    "as_of": None,
}
EXECUTION_ID = "failed-worker-job"
WORKER_ERROR = "Worker exhausted available memory"
STORED_ERROR = f"Simulation entrypoint execution failed: {WORKER_ERROR}"


@pytest.fixture(params=[SELECTION, None], ids=["canonical", "legacy"])
def failed_job_harness(request, monkeypatch):
    # Isolate bundle certification from this real route/service/cache replay test.
    # The fake worker reports an ordinary execution failure, with no SPM output.
    selection = request.param
    monkeypatch.setattr(worker_spm, "normalize_spm_selection", lambda *_: selection)
    gateway = Mock()
    gateway.get_spm_capability.return_value = {
        "contract_version": "canonical-spm-v1",
        "defaults": SELECTION,
    }
    gateway.resolve_app_name.side_effect = lambda country_id, version=None, **kwargs: (
        "test-worker",
        version,
    )
    gateway.get_execution_by_id.return_value = SimpleNamespace(error=WORKER_ERROR)
    gateway.get_execution_status.return_value = "failed"
    cache = ReformImpactCache(
        InMemoryCacheBackend(), CacheNamespace("test", "failed-job-replay")
    )
    impacts = ReformImpactsService(cache)
    service = EconomyService(
        reform_impacts_service_=impacts,
        simulation_entrypoint_=gateway,
    )
    setup = service._build_economic_impact_setup_options(
        country_id="us",
        policy_id=1,
        baseline_policy_id=2,
        region="us",
        dataset="default",
        time_period="2026",
        options={},
        api_version="1.0.0",
    )
    service._resolve_runtime_bundle_for_setup_options(setup)
    impacts.set_reform_impact(
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
        execution_id=EXECUTION_ID,
    )
    monkeypatch.setattr(economy_routes, "economy_service", service)
    logger = Mock()
    monkeypatch.setattr(economy_module, "logger", logger)
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(economy_routes.economy_bp)
    return app.test_client(), cache, gateway, logger, selection


def test_repeated_failed_polls_replay_failure_without_success_receipts(
    failed_job_harness,
):
    client, cache, gateway, logger, _ = failed_job_harness
    url = "/us/economy/1/over/2?region=us&time_period=2026&version=1.0.0"

    first = client.get(url)
    # An untyped upstream failure is the simulation service's, not the caller's.
    assert first.status_code == 502
    assert first.json == {"status": "error", "message": STORED_ERROR, "result": None}
    assert cache.get_by_execution_id(EXECUTION_ID).message == STORED_ERROR

    for _ in range(2):
        response = client.get(url)
        assert response.status_code == 502, response.json
        assert response.json == first.json
        stored = cache.get_by_execution_id(EXECUTION_ID)
        assert stored.status == "error"
        assert stored.message == STORED_ERROR
        assert stored.reform_impact_json == {}
        assert logger.log_struct.call_args.args[0] == {"message": STORED_ERROR}

    gateway.get_execution_by_id.assert_called_once_with(EXECUTION_ID)
    gateway.get_execution_result.assert_not_called()
    gateway.run.assert_not_called()


@pytest.mark.parametrize(
    "failed_job_harness", [SELECTION], indirect=True, ids=["canonical"]
)
def test_successful_cached_job_still_requires_canonical_receipts(failed_job_harness):
    client, cache, gateway, _, _ = failed_job_harness
    cache.update(EXECUTION_ID, status="ok", message="Completed")

    response = client.get(
        "/us/economy/1/over/2?region=us&time_period=2026&version=1.0.0"
    )

    assert response.status_code == 400
    assert response.json["errors"][0]["code"] == "SPM_CONFIGURATION_UNAVAILABLE"
    gateway.get_execution_by_id.assert_not_called()
    gateway.run.assert_not_called()


def test_annual_cliff_request_does_not_replay_general_failure(
    failed_job_harness, monkeypatch
):
    client, _, gateway, _, _ = failed_job_harness
    url = "/us/economy/1/over/2?region=us&time_period=2026&version=1.0.0"
    assert client.get(url).status_code == 502
    service = economy_routes.economy_service
    monkeypatch.setattr(service, "_get_policy_jsons", lambda *_: ({}, {}))
    gateway.run.return_value = SimpleNamespace(execution_id="new-cliff-job")
    gateway.get_execution_id.return_value = "new-cliff-job"
    response = client.get(url + "&target=cliff")
    assert response.status_code == 200, response.json
    assert response.json["status"] == "computing"
    assert gateway.run.call_count == 1
    assert gateway.run.call_args.args[0]["include_cliffs"] is True


@pytest.mark.parametrize("failed_job_harness", [None], indirect=True, ids=["legacy"])
def test_cliff_request_does_not_reuse_completed_general_result(
    failed_job_harness, monkeypatch
):
    client, cache, gateway, _, _ = failed_job_harness
    cache.update(
        EXECUTION_ID,
        status="ok",
        message="Completed",
        reform_impact_json={"cliff_impact": None, "resolved_app_name": "test-worker"},
    )
    url = "/us/economy/1/over/2?region=us&time_period=2026&version=1.0.0"
    assert client.get(url).status_code == 200
    service = economy_routes.economy_service
    monkeypatch.setattr(service, "_get_policy_jsons", lambda *_: ({}, {}))
    gateway.run.return_value = SimpleNamespace(execution_id="new-cliff-job")
    gateway.get_execution_id.return_value = "new-cliff-job"
    response = client.get(url + "&target=cliff")
    assert response.status_code == 200, response.json
    assert response.json["status"] == "computing"
    assert gateway.run.call_args.args[0]["include_cliffs"] is True
