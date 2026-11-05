"""Removing a stored reform-impact failure: only that failure, and only unchanged."""

from datetime import datetime

import pytest

from policyengine_api.runtime_cache.core import CacheCoordinationError, CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.reform_impacts import (
    CachedReformImpact,
    ReformImpactCache,
    ReformImpactIdentity,
    ReformImpactScope,
    reform_impact_id,
)

SCOPE = ReformImpactScope(
    country_id="us",
    reform_policy_id=2,
    baseline_policy_id=1,
    region="state/ca",
    dataset="default",
    time_period="2026",
)
OPTIONS_HASH = "[dataset=default&runtime_app_name=worker]"
IDENTITY = ReformImpactIdentity(
    scope=SCOPE, api_version="v1", options_hash=OPTIONS_HASH
)
FAILED_JOB = "failed-job"
NEWER_JOB = "newer-job"


def _computing(execution_id: str, day: int) -> CachedReformImpact:
    return CachedReformImpact(
        reform_impact_id=reform_impact_id(execution_id),
        baseline_policy_id=SCOPE.baseline_policy_id,
        reform_policy_id=SCOPE.reform_policy_id,
        country_id=SCOPE.country_id,
        region=SCOPE.region,
        dataset=SCOPE.dataset,
        time_period=SCOPE.time_period,
        options_json={},
        options_hash=OPTIONS_HASH,
        api_version=IDENTITY.api_version,
        reform_impact_json={},
        status="computing",
        message=None,
        start_time=datetime(2026, 1, day),
        end_time=None,
        execution_id=execution_id,
    )


@pytest.fixture
def backend() -> InMemoryCacheBackend:
    return InMemoryCacheBackend()


@pytest.fixture
def cache(backend: InMemoryCacheBackend) -> ReformImpactCache:
    return ReformImpactCache(backend, CacheNamespace("test", "failure-deletion"))


def _store_failure(
    cache: ReformImpactCache, **error_fields: object
) -> CachedReformImpact:
    assert cache.set(_computing(FAILED_JOB, day=1))
    failure = cache.update(
        FAILED_JOB,
        status="error",
        message="Worker exhausted available memory",
        end_time=datetime(2026, 1, 1, 0, 5),
        **error_fields,
    )
    assert failure is not None
    return failure


def _index_members(backend: InMemoryCacheBackend) -> set[str]:
    return {member for index in backend._sorted_sets.values() for member in index}


def test_delete_failure_removes_the_record_and_both_index_entries(
    cache: ReformImpactCache, backend: InMemoryCacheBackend
) -> None:
    failure = _store_failure(cache)

    deleted = cache.delete_failure(failure)

    assert deleted is True
    assert cache.get_by_execution_id(FAILED_JOB) is None
    assert cache.matching(IDENTITY) == []
    assert cache.recent(10) == []
    assert _index_members(backend) == set()


def test_delete_failure_finds_a_typed_failure_without_a_worker_handle(
    cache: ReformImpactCache, backend: InMemoryCacheBackend
) -> None:
    # A typed SPM failure clears its worker handle but keeps its record key.
    failure = _store_failure(
        cache, error_code="SPM_YEAR_UNAVAILABLE", clear_execution_id=True
    )
    assert failure.execution_id is None

    deleted = cache.delete_failure(failure)

    assert deleted is True
    assert cache.matching(IDENTITY) == []
    assert _index_members(backend) == set()


def test_delete_failure_leaves_the_scope_s_other_jobs(
    cache: ReformImpactCache,
) -> None:
    failure = _store_failure(cache)
    # A request submitted a newer job for the same scope at the same moment.
    newer_job = _computing(NEWER_JOB, day=2)
    assert cache.set(newer_job)

    deleted = cache.delete_failure(failure)

    assert deleted is True
    assert cache.matching(IDENTITY) == [newer_job]
    assert cache.recent(10) == [newer_job]


@pytest.mark.parametrize(
    "rewrite",
    [
        {"message": "A later poll recorded the failure again"},
        {"end_time": datetime(2026, 1, 1, 0, 9)},
    ],
    ids=["message", "end-time"],
)
def test_delete_failure_leaves_a_record_that_changed_after_it_was_read(
    cache: ReformImpactCache, rewrite: dict[str, object]
) -> None:
    failure = _store_failure(cache)
    rewritten = cache.update(FAILED_JOB, **rewrite)

    deleted = cache.delete_failure(failure)

    assert deleted is False
    assert cache.get_by_execution_id(FAILED_JOB) == rewritten
    assert cache.matching(IDENTITY) == [rewritten]


def test_delete_failure_reports_a_record_that_is_already_gone(
    cache: ReformImpactCache, backend: InMemoryCacheBackend
) -> None:
    failure = _store_failure(cache)
    assert cache.delete_failure(failure) is True

    assert cache.delete_failure(failure) is False
    assert _index_members(backend) == set()


@pytest.mark.parametrize("status", ["computing", "ok"])
def test_delete_failure_refuses_a_record_that_is_not_a_failure(
    cache: ReformImpactCache, status: str
) -> None:
    assert cache.set(_computing(FAILED_JOB, day=1))
    stored = cache.update(FAILED_JOB, status=status)

    with pytest.raises(ValueError, match="only a failed reform impact"):
        cache.delete_failure(stored)

    assert cache.get_by_execution_id(FAILED_JOB) == stored


def test_delete_failure_never_removes_a_record_that_became_a_completed_job(
    cache: ReformImpactCache,
) -> None:
    failure = _store_failure(cache)
    # Whatever rewrote the record, it no longer holds the failure read above.
    completed = cache.update(FAILED_JOB, status="ok", message="Completed")

    assert cache.delete_failure(failure) is False
    assert cache.get_by_execution_id(FAILED_JOB) == completed


@pytest.mark.parametrize("failing_operation", ["zrevrange", "get", "eval"])
def test_delete_failure_raises_when_the_cache_cannot_be_used(
    cache: ReformImpactCache,
    backend: InMemoryCacheBackend,
    monkeypatch: pytest.MonkeyPatch,
    failing_operation: str,
) -> None:
    failure = _store_failure(cache)

    def unreachable(*_args: object, **_kwargs: object) -> object:
        raise ConnectionError

    monkeypatch.setattr(backend, failing_operation, unreachable)

    with pytest.raises(CacheCoordinationError):
        cache.delete_failure(failure)
