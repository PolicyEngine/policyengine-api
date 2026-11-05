from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from policyengine_api import constants
from policyengine_api.constants import get_economy_impact_cache_version
from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.reform_impacts import (
    ReformImpactCache,
    ReformImpactIdentity,
    ReformImpactScope,
)
from policyengine_api.services.reform_impacts_service import (
    ReformImpactExecution,
    ReformImpactHandoffError,
    ReformImpactsService,
)

# Claim tokens are opaque ids that tell competing workers apart.
OWNER_CLAIM_TOKEN = "owner"
CONTENDER_CLAIM_TOKEN = "contender"
SCOPE = ReformImpactScope(
    country_id="us",
    reform_policy_id=2,
    baseline_policy_id=1,
    region="us",
    dataset="default",
    time_period="2026",
)


@pytest.fixture
def service():
    return ReformImpactsService(
        ReformImpactCache(
            InMemoryCacheBackend(),
            CacheNamespace("test", "api"),
        )
    )


def _create_impact(
    service,
    *,
    execution_id: str,
    options_hash: str,
    day: int,
):
    return service.set_reform_impact(
        ReformImpactIdentity(scope=SCOPE, api_version="1", options_hash=options_hash),
        ReformImpactExecution(
            execution_id=execution_id,
            start_time=datetime(2026, 1, day),
        ),
        options={"hash": options_hash},
        status="computing",
        reform_impact_json={},
    )


def test_set_reform_impact_fails_closed_when_execution_pointer_is_not_stored():
    cache = MagicMock(spec=ReformImpactCache)
    cache.set.return_value = False
    service = ReformImpactsService(cache)

    with pytest.raises(
        ReformImpactHandoffError,
        match="execution could not be stored",
    ):
        _create_impact(
            service,
            execution_id="submitted-job",
            options_hash="hash",
            day=1,
        )


def test_reform_impact_start_claim_is_exclusive_and_releasable(service):
    arguments = {
        "identity": ReformImpactIdentity(
            scope=SCOPE, api_version="1", options_hash="resolved-hash"
        ),
        "target": "general",
    }
    owner_observability_id = "00000000-0000-4000-8000-000000000001"
    contender_observability_id = "00000000-0000-4000-8000-000000000002"

    assert service.claim_reform_impact_start(
        **arguments,
        claim_token=OWNER_CLAIM_TOKEN,
        observability_id=owner_observability_id,
    )
    assert not service.claim_reform_impact_start(
        **arguments,
        claim_token=CONTENDER_CLAIM_TOKEN,
        observability_id=contender_observability_id,
    )
    claim = service.get_reform_impact_start_claim(**arguments)
    assert claim.submission_claim_id == OWNER_CLAIM_TOKEN
    assert claim.observability_id == owner_observability_id
    service.release_reform_impact_start(
        **arguments,
        claim_token=OWNER_CLAIM_TOKEN,
        observability_id=owner_observability_id,
    )
    assert service.claim_reform_impact_start(
        **arguments,
        claim_token=CONTENDER_CLAIM_TOKEN,
        observability_id=contender_observability_id,
    )


def test_reform_impact_service_round_trips_models_and_transitions(service):
    exact = _create_impact(
        service,
        execution_id="exact-job",
        options_hash="hash-exact",
        day=1,
    )
    compatible = _create_impact(
        service,
        execution_id="compatible-job",
        options_hash="hash-compatible",
        day=2,
    )

    exact_identity = ReformImpactIdentity(
        scope=SCOPE, api_version="1", options_hash="hash-exact"
    )
    exact_results = service.get_all_reform_impacts(exact_identity)
    compatible_results = service.get_all_reform_impacts_by_options_hash_prefix(
        exact_identity, "hash-%"
    )

    assert [impact.reform_impact_id for impact in exact_results] == [
        exact.reform_impact_id
    ]
    assert [impact.reform_impact_id for impact in compatible_results] == [
        exact.reform_impact_id,
        compatible.reform_impact_id,
    ]
    completed = service.set_complete_reform_impact(
        "exact-job", reform_impact_json={"result": 1}
    )
    failed = service.set_error_reform_impact("compatible-job", message="failed")

    assert completed.status == "ok"
    assert completed.reform_impact_json == {"result": 1}
    assert failed.status == "error"
    assert failed.message == "failed"


def test_reform_impact_service_deletes_only_matching_computing_rows(
    service,
):
    _create_impact(
        service,
        execution_id="delete-job",
        options_hash="delete-hash",
        day=1,
    )
    retained = _create_impact(
        service,
        execution_id="retain-job",
        options_hash="retain-hash",
        day=2,
    )

    service.delete_reform_impact(SCOPE, "delete-hash")

    remaining = service._cache.recent(10)
    assert all(impact.execution_id != "delete-job" for impact in remaining)
    assert any(
        impact.reform_impact_id == retained.reform_impact_id for impact in remaining
    )


def test_reform_impact_transitions_return_none_for_missing_execution(service):
    assert service.set_error_reform_impact("missing-job", message="missing") is None


def test_a_briefly_kept_error_expires_and_leaves_other_records() -> None:
    backend = InMemoryCacheBackend()
    service = ReformImpactsService(
        ReformImpactCache(backend, CacheNamespace("test", "api"))
    )
    _create_impact(service, execution_id="failed-job", options_hash="hash", day=1)
    _create_impact(service, execution_id="next-job", options_hash="hash", day=2)
    identity = ReformImpactIdentity(scope=SCOPE, api_version="1", options_hash="hash")

    failed = service.set_error_reform_impact(
        "failed-job", message="out of memory", keep_seconds=120
    )
    backend.advance(119)
    kept = service.get_all_reform_impacts(identity)
    backend.advance(2)
    after_expiry = service.get_all_reform_impacts(identity)

    assert failed is not None
    assert failed.status == "error"
    assert [(impact.execution_id, impact.status) for impact in kept] == [
        ("next-job", "computing"),
        ("failed-job", "error"),
    ]
    # Only the failed job's record expires; the next job's record is untouched.
    assert [(impact.execution_id, impact.status) for impact in after_expiry] == [
        ("next-job", "computing")
    ]


def test_a_failed_records_seconds_left_count_down_to_its_expiry() -> None:
    backend = InMemoryCacheBackend()
    service = ReformImpactsService(
        ReformImpactCache(backend, CacheNamespace("test", "api"))
    )
    _create_impact(service, execution_id="failed-job", options_hash="hash", day=1)
    stored_failure = service.set_error_reform_impact(
        "failed-job", message="out of memory", keep_seconds=120
    )

    backend.advance(30)

    assert service.get_reform_impact_seconds_left(stored_failure) == 90


def test_impact_cached_under_previous_economy_schema_version_is_not_matched(
    service,
):
    # Economy results cached under schema version 3 can hold decile relative
    # changes as percentages (x100) from the simulation API
    # (PolicyEngine/policyengine-sim-api#827). A lookup built from the
    # current cache version must not find them.
    current_cache_version = get_economy_impact_cache_version(SCOPE.country_id)
    with pytest.MonkeyPatch.context() as schema_version_patch:
        schema_version_patch.setitem(
            constants.RUNTIME_CACHE_SCHEMA_VERSIONS, "economy_impact", 3
        )
        percentage_decile_cache_version = get_economy_impact_cache_version(
            SCOPE.country_id
        )

    options_hash = "decile-hash"
    stale_identity = ReformImpactIdentity(
        scope=SCOPE,
        api_version=percentage_decile_cache_version,
        options_hash=options_hash,
    )
    service.set_reform_impact(
        stale_identity,
        ReformImpactExecution(
            execution_id="percentage-decile-job",
            start_time=datetime(2026, 7, 1),
        ),
        options={"hash": options_hash},
        status="computing",
        reform_impact_json={},
    )
    service.set_complete_reform_impact(
        "percentage-decile-job",
        reform_impact_json={"decile": {"relative": {"1": 1.5}}},
    )

    current_identity = ReformImpactIdentity(
        scope=SCOPE,
        api_version=current_cache_version,
        options_hash=options_hash,
    )

    assert [
        impact.execution_id for impact in service.get_all_reform_impacts(stale_identity)
    ] == ["percentage-decile-job"]
    assert service.get_all_reform_impacts(current_identity) == []
    assert (
        service.get_all_reform_impacts_by_options_hash_prefix(
            current_identity, f"{options_hash}%"
        )
        == []
    )


class ManualClock:
    """A naive-UTC clock that moves only when a test advances it."""

    def __init__(self) -> None:
        self.now = datetime(2026, 11, 5, 12, 0)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _clocked_service(clock: ManualClock) -> ReformImpactsService:
    return ReformImpactsService(
        ReformImpactCache(InMemoryCacheBackend(), CacheNamespace("test", "api")),
        now=clock,
    )


def test_seconds_until_counts_down_from_the_failure_s_end_time() -> None:
    clock = ManualClock()
    service = _clocked_service(clock)
    _create_impact(service, execution_id="failed-job", options_hash="hash", day=1)
    failure = service.set_error_reform_impact("failed-job", message="out of memory")

    at_once = service.get_reform_impact_seconds_until(failure, seconds_after_end=10)
    clock.advance(3.2)
    part_way = service.get_reform_impact_seconds_until(failure, seconds_after_end=10)
    clock.advance(6.8)
    at_the_end = service.get_reform_impact_seconds_until(failure, seconds_after_end=10)
    clock.advance(100)
    long_after = service.get_reform_impact_seconds_until(failure, seconds_after_end=10)

    # The failure's end time is the service clock's time when it was recorded.
    assert failure.end_time == datetime(2026, 11, 5, 12, 0)
    # Rounded up, so a caller that waits this long is never early.
    assert (at_once, part_way, at_the_end, long_after) == (10, 7, 0, 0)


def test_seconds_until_is_zero_without_an_end_time_and_never_above_the_wait() -> None:
    clock = ManualClock()
    service = _clocked_service(clock)
    computing = _create_impact(
        service, execution_id="old-job", options_hash="hash", day=1
    )
    # Recorded by an instance whose clock runs 30 seconds ahead of this one.
    from_a_clock_ahead = replace(
        computing, status="error", end_time=clock.now + timedelta(seconds=30)
    )

    without_end_time = service.get_reform_impact_seconds_until(
        replace(computing, status="error"), seconds_after_end=10
    )
    ahead = service.get_reform_impact_seconds_until(
        from_a_clock_ahead, seconds_after_end=10
    )

    assert without_end_time == 0
    assert ahead == 10


def test_delete_failed_reform_impact_removes_only_that_failure(service) -> None:
    _create_impact(service, execution_id="failed-job", options_hash="hash", day=1)
    _create_impact(service, execution_id="next-job", options_hash="hash", day=2)
    failure = service.set_error_reform_impact("failed-job", message="out of memory")
    identity = ReformImpactIdentity(scope=SCOPE, api_version="1", options_hash="hash")

    deleted = service.delete_failed_reform_impact(failure)
    deleted_again = service.delete_failed_reform_impact(failure)

    assert (deleted, deleted_again) == (True, False)
    assert [
        impact.execution_id for impact in service.get_all_reform_impacts(identity)
    ] == ["next-job"]
