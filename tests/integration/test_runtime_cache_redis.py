"""Real Redis qualification for cross-connection, TTL, atomicity, and claims."""

from datetime import datetime
import os
import time
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
import redis

from policyengine_api.runtime_cache.claims import ExpiringClaimStore
from policyengine_api.runtime_cache.core import CacheNamespace, RecoverableJSONCache
from policyengine_api.runtime_cache.household_traces import (
    HouseholdTraceCache,
    HouseholdTraceIdentity,
    HouseholdTraceValue,
)
from policyengine_api.runtime_cache.reform_impacts import (
    CachedReformImpact,
    ReformImpactCache,
    reform_impact_id,
)


RUNTIME_CACHE_TEST_URL = "RUNTIME_CACHE_TEST_URL"


@pytest.fixture
def redis_pair():
    raw_url = os.environ.get(RUNTIME_CACHE_TEST_URL, "")
    if not raw_url:
        pytest.skip(f"{RUNTIME_CACHE_TEST_URL} is not set")
    parsed = urlsplit(raw_url)
    if parsed.scheme != "redis" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        pytest.fail("real cache integration tests require explicit local Redis")
    if parsed.path not in {"", "/0"}:
        pytest.fail("real cache integration tests require disposable database 0")

    first = redis.Redis.from_url(raw_url, decode_responses=True)
    second = redis.Redis.from_url(raw_url, decode_responses=True)
    first.ping()
    prefix = f"policyengine:stage8-{uuid4().hex[:8]}:api:"
    try:
        yield first, second, CacheNamespace(prefix.split(":")[1], "api")
    finally:
        keys = list(first.scan_iter(match=f"{prefix}*"))
        if keys:
            first.delete(*keys)
        first.close()
        second.close()


def test_cross_connection_visibility_and_real_expiry(redis_pair) -> None:
    first, second, namespace = redis_pair
    writer = RecoverableJSONCache(
        first,
        namespace,
        family="integration",
        schema_version=1,
        ttl_seconds=3,
    )
    reader = RecoverableJSONCache(
        second,
        namespace,
        family="integration",
        schema_version=1,
        ttl_seconds=3,
    )
    assert writer.set({"input": "same"}, {"value": 42})
    assert reader.get({"input": "same"}) == {"value": 42}
    time.sleep(3.1)
    assert reader.get({"input": "same"}) is None


def test_atomic_household_tracer_value_is_shared_between_connections(
    redis_pair,
) -> None:
    first, second, namespace = redis_pair
    identity = HouseholdTraceIdentity(
        country_id="us",
        household_id=1,
        policy_id=2,
        household_hash="household",
        policy_hash="policy",
        country_package_version="1.2.3",
        policyengine_version="4.5.6",
    )
    value = HouseholdTraceValue(
        household={"people": {"you": {}}},
        tracer_output=["trace"],
    )
    assert HouseholdTraceCache(first, namespace).set(identity, value)
    assert HouseholdTraceCache(second, namespace).get(identity) == value


def test_real_claim_is_exclusive_token_safe_and_expires(redis_pair) -> None:
    first, second, namespace = redis_pair
    key = namespace.family_key("claims", 1, "work")
    first_claims = ExpiringClaimStore(first)
    second_claims = ExpiringClaimStore(second)
    assert first_claims.acquire(key, "first", ttl_seconds=1)
    assert not second_claims.acquire(key, "second", ttl_seconds=1)
    assert not second_claims.release(key, "second")
    time.sleep(1.1)
    assert second_claims.acquire(key, "second", ttl_seconds=1)
    assert second_claims.release(key, "second")


def test_reform_submission_claim_is_shared_across_connections(redis_pair) -> None:
    first, second, namespace = redis_pair
    writer = ReformImpactCache(first, namespace)
    contender = ReformImpactCache(second, namespace)
    arguments = {
        "country_id": "us",
        "reform_policy_id": 2,
        "baseline_policy_id": 1,
        "region": "us",
        "dataset": "default",
        "time_period": "2026",
        "api_version": "v1",
        "options_hash": "resolved-hash",
        "target": "general",
    }

    assert writer.claim_start(**arguments, claim_token="writer")
    assert not contender.claim_start(**arguments, claim_token="contender")
    assert not contender.release_start(**arguments, claim_token="contender")
    assert writer.release_start(**arguments, claim_token="writer")
    assert contender.claim_start(**arguments, claim_token="contender")


def test_real_reform_indexes_are_cross_connection_bounded_and_expiring(
    redis_pair,
    monkeypatch,
) -> None:
    import policyengine_api.runtime_cache.reform_impacts as module

    first, second, namespace = redis_pair
    monkeypatch.setattr(module, "REFORM_IMPACT_INDEX_LIMIT", 2)
    monkeypatch.setattr(module, "REFORM_IMPACT_TTL_SECONDS", 1)
    writer = ReformImpactCache(first, namespace)
    reader = ReformImpactCache(second, namespace)
    for day in range(1, 4):
        execution_id = f"job-{day}"
        assert writer.set(
            CachedReformImpact(
                reform_impact_id=reform_impact_id(execution_id),
                baseline_policy_id=1,
                reform_policy_id=2,
                country_id="us",
                region="us",
                dataset="default",
                time_period="2026",
                options_json={},
                options_hash=f"hash-{day}",
                api_version="v1",
                reform_impact_json={},
                status="computing",
                message=None,
                start_time=datetime(2026, 1, day),
                end_time=None,
                execution_id=execution_id,
            )
        )
    assert [impact.execution_id for impact in reader.recent(10)] == [
        "job-3",
        "job-2",
    ]
    time.sleep(1.1)
    assert reader.recent(10) == []
