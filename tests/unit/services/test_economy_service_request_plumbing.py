"""Characterization of how economy requests reach setup, caches and simulations.

These pin the complete resolved setup options, the cache records and keys, and
the simulation payloads, so a change in how request fields are passed between
the service's steps shows up as a difference here.
"""

import json
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

import pytest

from policyengine_api.libs.simulation_entrypoint import ModalSimulationExecution
from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.reform_impacts import (
    REFORM_IMPACT_INDEX_LIMIT,
    CachedReformImpact,
    ReformImpactCache,
    ReformImpactIdentity,
    ReformImpactScope,
    _like_matches,
    reform_impact_id,
)
from policyengine_api.services.budget_window_cache import BudgetWindowCache
from policyengine_api.services.economic_impact_request import EconomicImpactRequest
from policyengine_api.services.economy_service import (
    EconomicImpactResult,
    EconomyService,
    ImpactStatus,
    RuntimeBundleIdentity,
)
from policyengine_api.services.reform_impacts_service import ReformImpactsService
from tests.fixtures.libs.simulation_entrypoint import MOCK_LOCAL_AREA_BREAKDOWN_RESULT
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
    MockBatchProgress,
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
        patch(
            "policyengine_api.services.economy_budget_window_submission.resolve_observability_id",
            return_value=MOCK_OBSERVABILITY_ID,
        ),
        patch(
            "policyengine_api.services.economy_budget_window_submission.start_observability_id",
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
def reform_impact_backend():
    """Return the in-memory reform-impact cache, so a test can move its clock."""
    return InMemoryCacheBackend()


@pytest.fixture
def economy_service(
    service_environment,
    mock_simulation_entrypoint,
    reform_impact_backend,
):
    return EconomyService(
        reform_impacts_service_=ReformImpactsService(
            ReformImpactCache(reform_impact_backend, NAMESPACE)
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
            EconomicImpactRequest(
                country_id="us",
                policy_id=MOCK_POLICY_ID,
                baseline_policy_id=MOCK_BASELINE_POLICY_ID,
                region="ca",
                dataset="default",
                options=MOCK_OPTIONS,
                api_version=MOCK_API_VERSION,
                target=target,
            ),
            time_period="2025",
        )

    assert result == EconomicImpactResult.computing()
    assert captured == [_expected_setup(target=target)]


def test_annual_submission_stores_record_and_sends_payload(
    economy_service, mock_simulation_entrypoint, mock_datetime
):
    result = economy_service.get_economic_impact(
        EconomicImpactRequest(
            country_id="us",
            policy_id=MOCK_POLICY_ID,
            baseline_policy_id=MOCK_BASELINE_POLICY_ID,
            region="state/ca",
            dataset="default",
            options=MOCK_OPTIONS,
            api_version=MOCK_API_VERSION,
            target="cliff",
        ),
        time_period="2025",
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
        EconomicImpactRequest(
            country_id="us",
            policy_id=MOCK_POLICY_ID,
            baseline_policy_id=MOCK_BASELINE_POLICY_ID,
            region="ca",
            dataset="default",
            options=MOCK_OPTIONS,
            api_version=MOCK_API_VERSION,
        ),
        start_year="2026",
        window_size=3,
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
            batch_progress=MockBatchProgress(
                progress=None,
                completed_years=["2026"],
                running_years=["2027", "2028", "2029"],
                queued_years=[],
            ),
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


UK_BUNDLE_HASH_FIELDS = (
    f"dataset=default&model_version={MOCK_MODEL_VERSION}"
    f"&policyengine_version={MOCK_POLICYENGINE_VERSION}"
)
UK_NATIONAL_LOOKUP_HASH = f"[{UK_BUNDLE_HASH_FIELDS}]"
UK_BREAKDOWN_LOOKUP_HASH = f"[breakdown=local_areas&{UK_BUNDLE_HASH_FIELDS}]"


def _stored_options_hash(lookup_hash: str) -> str:
    """Return the hash a submission stores once its worker app is resolved."""
    return f"{lookup_hash[:-1]}&runtime_app_name={MOCK_RESOLVED_APP_NAME}]"


@pytest.fixture
def uk_package_versions(mock_country_package_versions):
    """Give the UK the mocked country model version the US fixtures use."""
    mock_country_package_versions["uk"] = MOCK_MODEL_VERSION


def _uk_request(options: dict, region: str = "uk") -> EconomicImpactRequest:
    return EconomicImpactRequest(
        country_id="uk",
        policy_id=MOCK_POLICY_ID,
        baseline_policy_id=MOCK_BASELINE_POLICY_ID,
        region=region,
        dataset="default",
        options=options,
        api_version=MOCK_API_VERSION,
    )


def _submitted_payload_fields(payload: dict) -> dict:
    """Return a submitted payload without its metadata and telemetry."""
    return {
        key: value
        for key, value in payload.items()
        if key not in {"_metadata", "_telemetry"}
    }


@pytest.mark.usefixtures("uk_package_versions")
def test_uk_breakdown_submission_has_its_own_hash_and_sends_breakdown(
    economy_service, mock_simulation_entrypoint
):
    result = economy_service.get_economic_impact(
        _uk_request({"breakdown": "local_areas"}), time_period="2026"
    )

    assert result == EconomicImpactResult.computing()
    payload = mock_simulation_entrypoint.run.call_args.args[0]
    assert _submitted_payload_fields(payload) == {
        "spm": None,
        "country": "uk",
        "scope": "macro",
        "reform": {"sample_param": {"2024-01-01.2100-12-31": 15}},
        "baseline": {},
        "time_period": "2026",
        "include_cliffs": False,
        "region": "uk",
        "model_version": MOCK_MODEL_VERSION,
        "policyengine_version": MOCK_POLICYENGINE_VERSION,
        "breakdown": "local_areas",
    }
    stored = economy_service._reform_impacts.get_recent_reform_impacts(5)
    assert [impact.options_hash for impact in stored] == [
        _stored_options_hash(UK_BREAKDOWN_LOOKUP_HASH)
    ]
    assert stored[0].options_json == {"breakdown": "local_areas"}


# The simulation API's TelemetryEnvelope forbids extra fields, so a breakdown
# is marked through the existing simulation_kind field, not a new one.
TELEMETRY_FIELDS = {
    "submission_claim_id",
    "requested_at",
    "simulation_kind",
    "geography_code",
    "geography_type",
    "config_hash",
    "capture_mode",
}


@pytest.mark.usefixtures("uk_package_versions")
@pytest.mark.parametrize(
    ("options", "region", "expected"),
    [
        (
            {"breakdown": "local_areas"},
            "uk",
            ("local_area_breakdown", "national", "uk"),
        ),
        (
            {"breakdown": "local_areas"},
            "country/scotland",
            ("local_area_breakdown", "country", "scotland"),
        ),
        ({}, "uk", ("national", "national", "uk")),
        ({}, "country/scotland", ("country", "country", "scotland")),
    ],
    ids=["breakdown-uk", "breakdown-scotland", "national-uk", "national-scotland"],
)
def test_uk_submission_telemetry_marks_breakdown_runs(
    economy_service, mock_simulation_entrypoint, options, region, expected
):
    economy_service.get_economic_impact(
        _uk_request(options, region=region), time_period="2026"
    )

    telemetry = mock_simulation_entrypoint.run.call_args.args[0]["_telemetry"]
    assert set(telemetry) == TELEMETRY_FIELDS
    assert (
        telemetry["simulation_kind"],
        telemetry["geography_type"],
        telemetry["geography_code"],
    ) == expected


@pytest.mark.usefixtures("uk_package_versions")
def test_uk_national_submission_sends_no_breakdown_and_keeps_its_hash(
    economy_service, mock_simulation_entrypoint
):
    economy_service.get_economic_impact(_uk_request({}), time_period="2026")

    payload = mock_simulation_entrypoint.run.call_args.args[0]
    assert "breakdown" not in payload
    stored = economy_service._reform_impacts.get_recent_reform_impacts(5)
    assert [impact.options_hash for impact in stored] == [
        _stored_options_hash(UK_NATIONAL_LOOKUP_HASH)
    ]


@pytest.mark.usefixtures("uk_package_versions")
def test_national_and_breakdown_hashes_never_match_each_others_lookup(
    economy_service,
):
    national, breakdown = (
        economy_service._build_economic_impact_setup_options(
            _uk_request(options), time_period="2026"
        ).options_hash
        for options in ({}, {"breakdown": "local_areas"})
    )
    assert (national, breakdown) == (
        UK_NATIONAL_LOOKUP_HASH,
        UK_BREAKDOWN_LOOKUP_HASH,
    )

    for lookup_hash, other_hash in ((national, breakdown), (breakdown, national)):
        pattern = economy_service._build_options_hash_lookup_pattern(lookup_hash)
        assert _like_matches(_stored_options_hash(lookup_hash), pattern)
        assert not _like_matches(other_hash, pattern)
        assert not _like_matches(_stored_options_hash(other_hash), pattern)


@pytest.mark.usefixtures("uk_package_versions")
def test_a_breakdown_request_never_reuses_the_national_job(
    economy_service, mock_simulation_entrypoint
):
    mock_simulation_entrypoint.get_execution_id.side_effect = [
        "national-job",
        "breakdown-job",
    ]
    economy_service.get_economic_impact(_uk_request({}), time_period="2026")
    economy_service.get_economic_impact(
        _uk_request({"breakdown": "local_areas"}), time_period="2026"
    )
    # A repeated breakdown request polls the breakdown job it already started.
    economy_service.get_economic_impact(
        _uk_request({"breakdown": "local_areas"}), time_period="2026"
    )

    submitted = [
        call.args[0].get("breakdown")
        for call in mock_simulation_entrypoint.run.call_args_list
    ]
    assert submitted == [None, "local_areas"]
    mock_simulation_entrypoint.get_execution_by_id.assert_called_once_with(
        "breakdown-job"
    )


@pytest.mark.usefixtures("uk_package_versions")
def test_a_northern_ireland_breakdown_sends_and_stores_the_registry_code(
    economy_service, mock_simulation_entrypoint
):
    request = _uk_request(
        {"breakdown": "local_areas"}, region="country/northern_ireland"
    )

    economy_service.get_economic_impact(request, time_period="2026")
    # The second request finds the stored job under the same region and polls it.
    economy_service.get_economic_impact(request, time_period="2026")

    payload = mock_simulation_entrypoint.run.call_args.args[0]
    assert payload["region"] == "country/northern_ireland"
    assert payload["breakdown"] == "local_areas"
    assert payload["_telemetry"]["geography_code"] == "northern_ireland"
    mock_simulation_entrypoint.run.assert_called_once()
    mock_simulation_entrypoint.get_execution_by_id.assert_called_once_with(
        MOCK_MODAL_JOB_ID
    )
    stored = economy_service._reform_impacts.get_recent_reform_impacts(5)
    assert [(impact.region, impact.options_json) for impact in stored] == [
        ("country/northern_ireland", {"breakdown": "local_areas"})
    ]
    assert stored[0].options_hash == _stored_options_hash(UK_BREAKDOWN_LOOKUP_HASH)


def _finish_jobs_with(
    simulation_entrypoint, *, status: str, result=None, error=None
) -> None:
    """Make every polled job report this status, result and error."""
    simulation_entrypoint.get_execution_by_id.side_effect = lambda job_id: (
        ModalSimulationExecution(
            job_id=job_id,
            status=status,
            result=result,
            error=error,
            resolved_app_name=MOCK_RESOLVED_APP_NAME,
        )
    )
    simulation_entrypoint.get_execution_status.side_effect = lambda execution: (
        execution.status
    )
    simulation_entrypoint.get_execution_result.side_effect = lambda execution: (
        execution.result
    )


BREAKDOWN_RETRY_NOTE = (
    "A new local-area breakdown can be requested 2 minutes after this failure."
)


@pytest.mark.usefixtures("uk_package_versions")
def test_a_failed_breakdown_is_returned_for_two_minutes_then_resubmitted(
    economy_service, mock_simulation_entrypoint, reform_impact_backend
):
    mock_simulation_entrypoint.get_execution_id.side_effect = [
        "first-breakdown-job",
        "second-breakdown-job",
    ]
    _finish_jobs_with(
        mock_simulation_entrypoint, status="failed", error="out of memory"
    )
    request = _uk_request({"breakdown": "local_areas"})

    economy_service.get_economic_impact(request, time_period="2026")
    failed = economy_service.get_economic_impact(request, time_period="2026")
    reform_impact_backend.advance(60)
    within_two_minutes = economy_service.get_economic_impact(
        request, time_period="2026"
    )
    reform_impact_backend.advance(61)
    retried = economy_service.get_economic_impact(request, time_period="2026")

    expected = EconomicImpactResult.error(
        f"Simulation entrypoint execution failed: out of memory. {BREAKDOWN_RETRY_NOTE}"
    )
    assert failed == expected
    # Within two minutes the stored failure is returned without a new job.
    assert within_two_minutes == expected
    mock_simulation_entrypoint.get_execution_by_id.assert_called_once_with(
        "first-breakdown-job"
    )
    # After that the record has expired and the next request submits again.
    assert retried == EconomicImpactResult.computing()
    assert mock_simulation_entrypoint.run.call_count == 2
    stored = economy_service._reform_impacts.get_recent_reform_impacts(5)
    assert [(impact.execution_id, impact.status) for impact in stored] == [
        ("second-breakdown-job", "computing")
    ]


@pytest.mark.usefixtures("uk_package_versions")
def test_a_failed_breakdown_is_recorded_after_a_thousand_newer_jobs(
    economy_service, mock_simulation_entrypoint, reform_impact_backend
):
    mock_simulation_entrypoint.get_execution_id.side_effect = [
        "old-breakdown-job",
        "new-breakdown-job",
    ]
    request = _uk_request({"breakdown": "local_areas"})
    economy_service.get_economic_impact(request, time_period="2026")
    # 1,000 newer economy jobs push the breakdown out of the recency index,
    # which keeps only the newest 1,000 records across every scope.
    cache = economy_service._reform_impacts._cache
    breakdown_record = cache.get_by_execution_id("old-breakdown-job")
    assert breakdown_record is not None
    for index in range(REFORM_IMPACT_INDEX_LIMIT):
        cache.set(
            replace(
                breakdown_record,
                reform_impact_id=index,
                region="country/wales",
                execution_id=f"newer-job-{index}",
                start_time=breakdown_record.start_time + timedelta(seconds=index + 1),
            )
        )
    assert "old-breakdown-job" not in {
        impact.execution_id for impact in cache.recent(REFORM_IMPACT_INDEX_LIMIT)
    }
    _finish_jobs_with(
        mock_simulation_entrypoint, status="failed", error="out of memory"
    )

    failed = economy_service.get_economic_impact(request, time_period="2026")
    reform_impact_backend.advance(121)
    retried = economy_service.get_economic_impact(request, time_period="2026")

    assert failed.status == ImpactStatus.ERROR
    assert retried == EconomicImpactResult.computing()
    assert mock_simulation_entrypoint.run.call_count == 2
    mock_simulation_entrypoint.get_execution_by_id.assert_called_once_with(
        "old-breakdown-job"
    )


@pytest.mark.usefixtures("uk_package_versions")
def test_a_late_poll_of_a_failed_breakdown_leaves_the_next_job_alone(
    economy_service, mock_simulation_entrypoint
):
    mock_simulation_entrypoint.get_execution_id.side_effect = ["first-breakdown-job"]
    request = _uk_request({"breakdown": "local_areas"})
    economy_service.get_economic_impact(request, time_period="2026")
    cache = economy_service._reform_impacts._cache
    first_record = cache.get_by_execution_id("first-breakdown-job")
    assert first_record is not None
    # A Retry elsewhere has already stored the next job for the same scope and
    # options hash, also computing.
    cache.set(
        replace(
            first_record,
            reform_impact_id=first_record.reform_impact_id + 1,
            execution_id="second-breakdown-job",
            start_time=first_record.start_time + timedelta(seconds=1),
        )
    )
    setup_options = economy_service._build_economic_impact_setup_options(
        request, time_period="2026"
    )
    economy_service._resolve_runtime_bundle_for_setup_options(setup_options)

    # A slow poller that read the first job before the Retry now sees it fail.
    result = economy_service._handle_execution_state(
        setup_options=setup_options,
        execution_state="failed",
        reform_impact=first_record,
        execution=ModalSimulationExecution(
            job_id="first-breakdown-job", status="failed", error="out of memory"
        ),
    )

    assert result.status == ImpactStatus.ERROR
    second_record = cache.get_by_execution_id("second-breakdown-job")
    assert second_record is not None
    assert second_record.status == "computing"


@pytest.mark.usefixtures("uk_package_versions")
def test_a_failed_national_job_is_still_replayed(
    economy_service, mock_simulation_entrypoint, reform_impact_backend
):
    _finish_jobs_with(
        mock_simulation_entrypoint, status="failed", error="out of memory"
    )
    request = _uk_request({})

    economy_service.get_economic_impact(request, time_period="2026")
    failed = economy_service.get_economic_impact(request, time_period="2026")
    reform_impact_backend.advance(121)
    replayed = economy_service.get_economic_impact(request, time_period="2026")

    expected = EconomicImpactResult.error(
        "Simulation entrypoint execution failed: out of memory"
    )
    assert failed == expected
    assert replayed == expected
    mock_simulation_entrypoint.run.assert_called_once()
    mock_simulation_entrypoint.get_execution_by_id.assert_called_once()
    stored = economy_service._reform_impacts.get_recent_reform_impacts(5)
    assert [impact.status for impact in stored] == ["error"]


@pytest.mark.usefixtures("uk_package_versions")
@pytest.mark.parametrize(
    ("result", "reported_kind"),
    [
        ({"budget": {"budgetary_impact": 1.0}}, "None"),
        ({**MOCK_LOCAL_AREA_BREAKDOWN_RESULT, "kind": "national"}, "'national'"),
        (None, "None"),
    ],
    ids=["national-result", "other-kind", "no-result"],
)
def test_a_breakdown_job_without_a_local_areas_result_is_not_stored(
    economy_service,
    mock_simulation_entrypoint,
    reform_impact_backend,
    result,
    reported_kind,
):
    mock_simulation_entrypoint.get_execution_id.side_effect = [
        "first-breakdown-job",
        "second-breakdown-job",
    ]
    _finish_jobs_with(mock_simulation_entrypoint, status="complete", result=result)
    request = _uk_request({"breakdown": "local_areas"})

    economy_service.get_economic_impact(request, time_period="2026")
    completed = economy_service.get_economic_impact(request, time_period="2026")
    within_two_minutes = economy_service.get_economic_impact(
        request, time_period="2026"
    )
    reform_impact_backend.advance(121)
    retried = economy_service.get_economic_impact(request, time_period="2026")

    expected = EconomicImpactResult.error(
        "The simulation API returned a result of kind "
        f"{reported_kind} for a local-area breakdown request, which needs kind "
        f"'local_areas'; the result was not stored. {BREAKDOWN_RETRY_NOTE}"
    )
    assert completed == expected
    assert within_two_minutes == expected
    assert retried == EconomicImpactResult.computing()
    assert mock_simulation_entrypoint.run.call_count == 2
    stored = economy_service._reform_impacts.get_recent_reform_impacts(5)
    assert [(impact.execution_id, impact.status) for impact in stored] == [
        ("second-breakdown-job", "computing")
    ]


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
        options={"b": {"c": 2}, "a": 1}, bundle=RuntimeBundleIdentity(**bundle_fields)
    )

    assert options_hash == expected


def test_options_hash_marks_spm_provenance_schema():
    options_hash = EconomyService()._build_options_hash(
        options={"spm": {"scenario": "x"}},
        bundle=RuntimeBundleIdentity(
            dataset="default", model_version="1", runtime_app_name="app"
        ),
    )

    assert options_hash == (
        "[spm={'scenario': 'x'}&dataset=default&model_version=1"
        "&spm_provenance_schema=canonical-spm-comparison-v2&runtime_app_name=app]"
    )


def test_empty_options_hash_drops_the_leading_separator():
    options_hash = EconomyService()._build_options_hash(
        options={}, bundle=RuntimeBundleIdentity(dataset="default", model_version="1")
    )

    assert options_hash == "[dataset=default&model_version=1]"
    assert json.dumps(options_hash)
