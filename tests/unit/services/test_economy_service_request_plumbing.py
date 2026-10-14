"""Characterization of how economy requests reach setup, caches and simulations.

These pin the complete resolved setup options, the cache records and keys, and
the simulation payloads, so a change in how request fields are passed between
the service's steps shows up as a difference here.
"""

import json
from unittest.mock import patch

import pytest

from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.reform_impacts import (
    CachedReformImpact,
    ReformImpactCache,
    ReformImpactIdentity,
    ReformImpactScope,
    reform_impact_id,
)
from policyengine_api.services.budget_window_cache import BudgetWindowCache
from policyengine_api.services.economy_service import (
    EconomicImpactResult,
    EconomyService,
)
from policyengine_api.services.reform_impacts_service import ReformImpactsService
from tests.fixtures.services.economy_service import (
    MOCK_API_VERSION,
    MOCK_BASELINE_POLICY_ID,
    MOCK_LOOKUP_OPTIONS_HASH,
    MOCK_MODAL_JOB_ID,
    MOCK_MODEL_VERSION,
    MOCK_OBSERVABILITY_ID,
    MOCK_OPTIONS,
    MOCK_OPTIONS_HASH,
    MOCK_POLICY_ID,
    MOCK_POLICYENGINE_VERSION,
    MOCK_RESOLVED_APP_NAME,
    MOCK_SUBMISSION_CLAIM_ID,
    create_mock_budget_window_batch_execution,
)
from tests.fixtures.spm import resolved_options

pytest_plugins = ("tests.fixtures.services.economy_service",)

NAMESPACE = CacheNamespace("test", "api")
CACHE_VERSION = "economy-cache-version"


@pytest.fixture
def stable_identifiers(
    mock_submission_claim_id,
    mock_datetime,
):
    """Fix the cache version, the clock and every identifier the service mints."""
    with (
        patch(
            "policyengine_api.services.economy_service.get_economy_impact_cache_version",
            return_value=CACHE_VERSION,
        ),
        patch(
            "policyengine_api.services.economy_service.resolve_observability_id",
            return_value=MOCK_OBSERVABILITY_ID,
        ),
        patch(
            "policyengine_api.services.economy_service.start_observability_id",
            side_effect=lambda value: value,
        ),
    ):
        yield


@pytest.fixture
def service_environment(
    mock_country_package_versions,
    mock_policyengine_version,
    mock_policy_service,
    mock_logger,
    stable_identifiers,
):
    """Pin package versions, policies, logging and identifiers for one service.

    Every argument is requested for its side effect, since usefixtures marks
    don't apply to fixtures.
    """


@pytest.fixture
def economy_service(
    service_environment,
    mock_simulation_entrypoint,
):
    return EconomyService(
        reform_impacts_service_=ReformImpactsService(
            ReformImpactCache(InMemoryCacheBackend(), NAMESPACE)
        ),
        budget_window_cache_=BudgetWindowCache(InMemoryCacheBackend(), NAMESPACE),
        simulation_entrypoint_=mock_simulation_entrypoint,
    )


def _expected_setup(**changes: object) -> dict:
    values = {
        "submission_claim_id": MOCK_SUBMISSION_CLAIM_ID,
        "observability_id": None,
        "country_id": "us",
        "reform_policy_id": MOCK_POLICY_ID,
        "baseline_policy_id": MOCK_BASELINE_POLICY_ID,
        "region": "state/ca",
        "dataset": "default",
        "time_period": "2025",
        "options": resolved_options(MOCK_OPTIONS),
        "api_version": CACHE_VERSION,
        "target": "general",
        "model_version": MOCK_MODEL_VERSION,
        "policyengine_version": MOCK_POLICYENGINE_VERSION,
        "data_version": None,
        "runtime_app_name": None,
        "options_hash": MOCK_LOOKUP_OPTIONS_HASH,
    }
    values.update(changes)
    return values


@pytest.mark.parametrize("target", ["general", "cliff"])
def test_annual_request_resolves_complete_setup_options(economy_service, target):
    captured = []

    def capture(_service, setup_options):
        captured.append(setup_options.model_dump())
        return EconomicImpactResult.computing()

    with patch.object(EconomyService, "_get_or_create_economic_impact", capture):
        result = economy_service.get_economic_impact(
            country_id="us",
            policy_id=MOCK_POLICY_ID,
            baseline_policy_id=MOCK_BASELINE_POLICY_ID,
            region="ca",
            dataset="default",
            time_period="2025",
            options=MOCK_OPTIONS,
            api_version=MOCK_API_VERSION,
            target=target,
        )

    assert result == EconomicImpactResult.computing()
    assert captured == [_expected_setup(target=target)]


def test_annual_submission_stores_record_and_sends_payload(
    economy_service, mock_simulation_entrypoint, mock_datetime
):
    result = economy_service.get_economic_impact(
        country_id="us",
        policy_id=MOCK_POLICY_ID,
        baseline_policy_id=MOCK_BASELINE_POLICY_ID,
        region="state/ca",
        dataset="default",
        time_period="2025",
        options=MOCK_OPTIONS,
        api_version=MOCK_API_VERSION,
        target="cliff",
    )

    assert result == EconomicImpactResult.computing()
    payload = mock_simulation_entrypoint.run.call_args.args[0]
    config_hash = payload["_telemetry"].pop("config_hash")
    assert config_hash.startswith("sha256:")
    assert payload == {
        "spm": resolved_options({}).get("spm"),
        "country": "us",
        "scope": "macro",
        "reform": {"sample_param": {"2024-01-01.2100-12-31": 15}},
        "baseline": {},
        "time_period": "2025",
        "include_cliffs": True,
        "region": "state/ca",
        "model_version": MOCK_MODEL_VERSION,
        "policyengine_version": MOCK_POLICYENGINE_VERSION,
        "_metadata": {
            "reform_policy_id": MOCK_POLICY_ID,
            "baseline_policy_id": MOCK_BASELINE_POLICY_ID,
            "submission_claim_id": MOCK_SUBMISSION_CLAIM_ID,
            "model_version": MOCK_MODEL_VERSION,
            "policyengine_version": MOCK_POLICYENGINE_VERSION,
            "data_version": None,
            "dataset": "default",
            "resolved_app_name": MOCK_RESOLVED_APP_NAME,
        },
        "_telemetry": {
            "submission_claim_id": MOCK_SUBMISSION_CLAIM_ID,
            "requested_at": payload["_telemetry"]["requested_at"],
            "simulation_kind": "state",
            "geography_code": "ca",
            "geography_type": "state",
            "capture_mode": "disabled",
        },
    }
    stored = economy_service._reform_impacts.get_recent_reform_impacts(5)
    assert stored == [
        CachedReformImpact(
            reform_impact_id=reform_impact_id(MOCK_MODAL_JOB_ID),
            baseline_policy_id=MOCK_BASELINE_POLICY_ID,
            reform_policy_id=MOCK_POLICY_ID,
            country_id="us",
            region="state/ca",
            dataset="default",
            time_period="2025",
            options_json=resolved_options(MOCK_OPTIONS),
            options_hash=MOCK_OPTIONS_HASH,
            api_version=CACHE_VERSION,
            reform_impact_json={},
            status="computing",
            message=None,
            start_time=mock_datetime.now.return_value,
            end_time=None,
            execution_id=MOCK_MODAL_JOB_ID,
            error_code=None,
            observability_id=MOCK_OBSERVABILITY_ID,
        )
    ]
    # The submission claim is released once the execution pointer is stored.
    assert (
        economy_service._reform_impacts.get_reform_impact_start_claim(
            identity=ReformImpactIdentity(
                scope=_scope(time_period="2025"),
                api_version=CACHE_VERSION,
                options_hash=MOCK_OPTIONS_HASH,
            ),
            target="cliff",
        )
        is None
    )


def _scope(time_period: str) -> ReformImpactScope:
    return ReformImpactScope(
        country_id="us",
        reform_policy_id=MOCK_POLICY_ID,
        baseline_policy_id=MOCK_BASELINE_POLICY_ID,
        region="state/ca",
        dataset="default",
        time_period=time_period,
    )


def _budget_window_key(service: EconomyService) -> str:
    return service._budget_window_cache.build_key(
        _scope(time_period="budget_window:2026:3"),
        options_hash=MOCK_LOOKUP_OPTIONS_HASH,
        api_version=CACHE_VERSION,
    )


def _request_budget_window(service: EconomyService) -> dict:
    result = service.get_budget_window_economic_impact(
        country_id="us",
        policy_id=MOCK_POLICY_ID,
        baseline_policy_id=MOCK_BASELINE_POLICY_ID,
        region="ca",
        dataset="default",
        start_year="2026",
        window_size=3,
        options=MOCK_OPTIONS,
        api_version=MOCK_API_VERSION,
        max_active_years=2,
    )
    return {**result.to_dict(), "cache_status": result.cache_status}


def test_budget_window_with_a_starting_claim_reports_every_year_queued(
    economy_service, mock_simulation_entrypoint
):
    key = _budget_window_key(economy_service)
    assert economy_service._budget_window_cache.claim_batch_start(
        key, "another-request", MOCK_OBSERVABILITY_ID
    )

    assert _request_budget_window(economy_service) == {
        "status": "computing",
        "data": None,
        "progress": 0,
        "completed_years": [],
        "computing_years": [],
        "queued_years": ["2026", "2027", "2028"],
        "message": "Queued 2026 (0 of 3 complete)...",
        "error": None,
        "cache_status": "starting-claim-hit",
    }
    mock_simulation_entrypoint.run_budget_window_batch.assert_not_called()


def test_budget_window_submission_stores_state_and_sends_payload(
    economy_service, mock_simulation_entrypoint
):
    mock_simulation_entrypoint.run_budget_window_batch.return_value = (
        create_mock_budget_window_batch_execution(batch_job_id="batch-7")
    )

    result = _request_budget_window(economy_service)

    assert result == {
        "status": "computing",
        "data": None,
        "progress": 0,
        "completed_years": [],
        "computing_years": [],
        "queued_years": ["2026", "2027", "2028"],
        "message": "Queued 2026 (0 of 3 complete)...",
        "error": None,
        "cache_status": "miss",
    }
    payload = mock_simulation_entrypoint.run_budget_window_batch.call_args.args[0]
    assert payload == {
        "spm": resolved_options({}).get("spm"),
        "country": "us",
        "scope": "macro",
        "reform": {"sample_param": {"2024-01-01.2100-12-31": 15}},
        "baseline": {},
        "include_cliffs": False,
        "region": "state/ca",
        "model_version": MOCK_MODEL_VERSION,
        "policyengine_version": MOCK_POLICYENGINE_VERSION,
        "start_year": "2026",
        "window_size": 3,
        "max_parallel": 2,
        "target": "general",
    }
    state = economy_service._budget_window_cache.get_state(
        _budget_window_key(economy_service)
    )
    assert state is not None
    assert state.to_payload() == {
        "status": "submitted",
        "observability_id": MOCK_OBSERVABILITY_ID,
        "batch_job_id": "batch-7",
    }


def test_budget_window_poll_reports_running_years(
    economy_service, mock_simulation_entrypoint
):
    mock_simulation_entrypoint.run_budget_window_batch.return_value = (
        create_mock_budget_window_batch_execution(batch_job_id="batch-7")
    )
    _request_budget_window(economy_service)
    mock_simulation_entrypoint.get_budget_window_batch_by_id.return_value = (
        create_mock_budget_window_batch_execution(
            batch_job_id="batch-7",
            status="running",
            progress=None,
            completed_years=["2026"],
            running_years=["2027", "2028", "2029"],
            queued_years=[],
        )
    )

    result = _request_budget_window(economy_service)

    assert result == {
        "status": "computing",
        "data": None,
        "progress": 33,
        "completed_years": ["2026"],
        "computing_years": ["2027", "2028", "2029"],
        "queued_years": [],
        "message": "Scoring 2027, 2028 + 1 more (1 of 3 complete)...",
        "error": None,
        "cache_status": "batch-id-hit",
    }
    mock_simulation_entrypoint.get_budget_window_batch_by_id.assert_called_once_with(
        "batch-7"
    )


@pytest.mark.parametrize(
    ("bundle_fields", "expected"),
    [
        (
            {"model_version": "1.2.3", "dataset": "default"},
            "[a=1&b={'c': 2}&dataset=default&model_version=1.2.3]",
        ),
        (
            {
                "model_version": None,
                "dataset": "hf://data.h5@2",
                "runtime_app_name": "app-1",
                "data_version": "2",
                "policyengine_version": "3.4.0",
            },
            "[a=1&b={'c': 2}&dataset=hf://data.h5@2&model_version=None"
            "&data_version=2&policyengine_version=3.4.0&runtime_app_name=app-1]",
        ),
    ],
)
def test_options_hash_lists_options_then_bundle_fields(bundle_fields, expected):
    options_hash = EconomyService()._build_options_hash(
        options={"b": {"c": 2}, "a": 1}, **bundle_fields
    )

    assert options_hash == expected


def test_options_hash_marks_spm_provenance_schema():
    options_hash = EconomyService()._build_options_hash(
        options={"spm": {"scenario": "x"}},
        model_version="1",
        dataset="default",
        runtime_app_name="app",
    )

    assert options_hash == (
        "[spm={'scenario': 'x'}&dataset=default&model_version=1"
        "&spm_provenance_schema=canonical-spm-comparison-v2&runtime_app_name=app]"
    )


def test_empty_options_hash_drops_the_leading_separator():
    options_hash = EconomyService()._build_options_hash(
        options={}, model_version="1", dataset="default"
    )

    assert options_hash == "[dataset=default&model_version=1]"
    assert json.dumps(options_hash)
