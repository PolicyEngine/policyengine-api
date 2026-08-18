"""Typed runtime-cache repository tests."""

from datetime import datetime

from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.repositories import (
    AIAnalysisCache,
    CachedAnalysis,
    CachedReformImpact,
    HouseholdTraceCache,
    HouseholdTraceIdentity,
    HouseholdTraceValue,
    ReformImpactCache,
    REFORM_IMPACT_START_CLAIM_TTL_SECONDS,
    reform_impact_id,
)


def _namespace() -> CacheNamespace:
    return CacheNamespace("test", "api")


def _identity(**changes) -> HouseholdTraceIdentity:
    values = {
        "country_id": "us",
        "household_id": 1,
        "policy_id": 2,
        "household_hash": "household-a",
        "policy_hash": "policy-a",
        "country_package_version": "1.2.3",
        "policyengine_version": "4.5.6",
    }
    values.update(changes)
    return HouseholdTraceIdentity(**values)


def test_household_and_tracer_share_one_atomic_versioned_value() -> None:
    backend = InMemoryCacheBackend()
    cache = HouseholdTraceCache(backend, _namespace())
    value = HouseholdTraceValue(
        household={"people": {"you": {"income": {"2026": 42}}}},
        tracer_output=["income <2026>"],
    )
    identity = _identity()

    assert cache.set(identity, value) is True
    assert cache.get(identity) == value
    assert list(backend._values) == [cache.cache_key(identity)]
    assert cache.cache_key(identity) != cache.cache_key(
        _identity(household_hash="household-b")
    )
    assert cache.cache_key(identity) != cache.cache_key(
        _identity(country_package_version="9.9.9")
    )


def test_analysis_cache_is_model_and_prompt_specific_and_expiring() -> None:
    backend = InMemoryCacheBackend()
    cache = AIAnalysisCache(backend, _namespace())
    value = CachedAnalysis(prompt="explain", analysis="answer")
    assert cache.set(value, model="model-a") is True
    assert cache.get("explain", model="model-a") == value
    assert cache.get("explain", model="model-b") is None
    assert cache.get("different", model="model-a") is None


def _impact(execution_id: str, options_hash: str, day: int) -> CachedReformImpact:
    return CachedReformImpact(
        reform_impact_id=reform_impact_id(execution_id),
        baseline_policy_id=1,
        reform_policy_id=2,
        country_id="us",
        region="us",
        dataset="default",
        time_period="2026",
        options_json={"hash": options_hash},
        options_hash=options_hash,
        api_version="v1",
        reform_impact_json={},
        status="computing",
        message=None,
        start_time=datetime(2026, 1, day),
        end_time=None,
        execution_id=execution_id,
    )


def _claim_arguments(**changes):
    values = {
        "country_id": "us",
        "reform_policy_id": 2,
        "baseline_policy_id": 1,
        "region": "us",
        "dataset": "default",
        "time_period": "2026",
        "api_version": "v1",
        "options_hash": "hash",
        "target": "general",
    }
    values.update(changes)
    return values


def test_reform_impact_start_claim_is_atomic_exact_ttl_and_token_safe() -> None:
    backend = InMemoryCacheBackend()
    cache = ReformImpactCache(backend, _namespace())
    arguments = _claim_arguments()

    assert cache.claim_start(**arguments, claim_token="owner") is True
    assert cache.claim_start(**arguments, claim_token="contender") is False
    assert (
        cache.claim_start(
            **_claim_arguments(target="cliff"),
            claim_token="cliff-owner",
        )
        is True
    )
    assert set(backend._expires.values()) == {REFORM_IMPACT_START_CLAIM_TTL_SECONDS}

    assert cache.release_start(**arguments, claim_token="contender") is False
    assert cache.release_start(**arguments, claim_token="owner") is True
    assert cache.claim_start(**arguments, claim_token="next-owner") is True


def test_reform_impact_indexes_are_bounded_expiring_and_query_compatible(
    monkeypatch,
) -> None:
    import policyengine_api.runtime_cache.repositories as module

    monkeypatch.setattr(module, "REFORM_IMPACT_INDEX_LIMIT", 2)
    backend = InMemoryCacheBackend()
    cache = ReformImpactCache(backend, _namespace())
    exact = _impact("exact", "hash-exact", 1)
    compatible = _impact("compatible", "hash-compatible", 2)
    newest = _impact("newest", "hash-newest", 3)
    assert cache.set(exact)
    assert cache.set(compatible)
    assert cache.set(newest)

    assert [value.execution_id for value in cache.recent(10)] == [
        "newest",
        "compatible",
    ]
    results = cache.matching(
        country_id="us",
        reform_policy_id=2,
        baseline_policy_id=1,
        region="us",
        dataset="default",
        time_period="2026",
        api_version="v1",
        options_hash="hash-compatible",
        options_hash_pattern="hash-%",
    )
    assert [value.execution_id for value in results] == [
        "compatible",
        "newest",
    ]
    backend.advance(module.REFORM_IMPACT_TTL_SECONDS)
    assert cache.recent(10) == []


def test_reform_impact_record_and_indexes_share_one_jittered_ttl(
    monkeypatch,
) -> None:
    import policyengine_api.runtime_cache.repositories as module

    monkeypatch.setattr(module, "jittered_ttl", lambda _ttl: 123)
    backend = InMemoryCacheBackend()
    cache = ReformImpactCache(backend, _namespace())

    assert cache.set(_impact("jittered", "hash", 1))
    assert len(backend._expires) == 3
    assert set(backend._expires.values()) == {123}


def test_reform_impact_updates_and_deletes_only_matching_computing_values() -> None:
    backend = InMemoryCacheBackend()
    cache = ReformImpactCache(backend, _namespace())
    deleted = _impact("delete", "delete-hash", 1)
    retained = _impact("retain", "retain-hash", 2)
    cache.set(deleted)
    cache.set(retained)

    completed = cache.update(
        "retain",
        status="ok",
        message="Completed",
        reform_impact_json={"result": 1},
    )
    assert completed is not None
    assert completed.status == "ok"
    cache.delete_matching_computing(
        country_id="us",
        reform_policy_id=2,
        baseline_policy_id=1,
        region="us",
        dataset="default",
        time_period="2026",
        options_hash="delete-hash",
    )
    assert cache.get_by_execution_id("delete") is None
    assert cache.get_by_execution_id("retain") is not None
