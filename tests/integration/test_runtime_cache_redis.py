"""Real Redis qualification for cross-connection, TTL, atomicity, and claims."""

import os
import time
from datetime import datetime
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
import redis

from policyengine_api.runtime_cache.claims import ExpiringClaimStore
from policyengine_api.runtime_cache.core import CacheNamespace, RecoverableJSONCache
from policyengine_api.runtime_cache.household_calculations import (
    CachedHouseholdCalculation,
    HouseholdCalculationCache,
    HouseholdCalculationIdentity,
)
from policyengine_api.runtime_cache.reform_impacts import (
    CachedReformImpact,
    ReformImpactCache,
    ReformImpactIdentity,
    ReformImpactScope,
    reform_impact_id,
)

RUNTIME_CACHE_TEST_URL = "RUNTIME_CACHE_TEST_URL"
# Claim tokens are opaque ids that tell competing workers apart.
WRITER_CLAIM_TOKEN = "writer"
CONTENDER_CLAIM_TOKEN = "contender"


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


def test_cached_household_calculation_is_shared_between_connections(
    redis_pair,
) -> None:
    first, second, namespace = redis_pair
    identity = HouseholdCalculationIdentity(
        country_id="us",
        household_id=1,
        policy_id=2,
        household_hash="household",
        policy_hash="policy",
        country_package_version="1.2.3",
        policyengine_version="4.5.6",
    )
    value = CachedHouseholdCalculation(
        household={"people": {"you": {}}},
        warnings=("calculation warning",),
    )
    assert HouseholdCalculationCache(first, namespace).set(identity, value)
    assert HouseholdCalculationCache(second, namespace).get(identity) == value


def test_cached_calculation_receipts_survive_a_real_round_trip(redis_pair) -> None:
    """Key cached calculations by SPM selection and keep their receipts.

    The selection is part of cache identity and its receipts travel with the
    result, so a replay under the same measurement reads back a complete receipt
    and a replay under a different one misses.
    """
    first, second, namespace = redis_pair
    selection = {
        "forecast_content_sha256": "c" * 64,
        "scenario": "baseline",
        "geography_kind": "national",
        "geography_id": None,
        "county_vintage": "2020",
        "as_of": None,
    }
    identity = HouseholdCalculationIdentity(
        country_id="us",
        household_id=3,
        policy_id=4,
        household_hash="household",
        policy_hash="policy",
        country_package_version="1.2.3",
        policyengine_version="4.5.6",
        spm=selection,
    )
    value = CachedHouseholdCalculation(
        household={"people": {"you": {}}},
        warnings=(),
        spm_provenance={
            "schema_version": "canonical-spm-provenance-v2",
            "forecast_id": "test-artifact",
            "forecast_sha256": selection["forecast_content_sha256"],
            "scenario": "baseline",
            "geography_kind": "national",
            "geography_id": None,
            "county_vintage": "2020",
            "as_of": None,
            "runtime_versions": {
                "policyengine": "test-only",
                "policyengine-core": "test-only",
                "policyengine-us": "test-only",
                "spm-calculator": "test-only",
            },
            "years": ["2026"],
        },
    )

    assert HouseholdCalculationCache(first, namespace).set(identity, value)
    cached = HouseholdCalculationCache(second, namespace).get(identity)
    assert cached is not None
    assert cached.spm_provenance == value.spm_provenance
    other = HouseholdCalculationIdentity(
        **{**vars(identity), "spm": {**selection, "geography_kind": "county"}}
    )
    assert HouseholdCalculationCache(second, namespace).get(other) is None


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
        "identity": ReformImpactIdentity(
            scope=ReformImpactScope(
                country_id="us",
                reform_policy_id=2,
                baseline_policy_id=1,
                region="us",
                dataset="default",
                time_period="2026",
            ),
            api_version="v1",
            options_hash="resolved-hash",
        ),
        "target": "general",
    }
    writer_observability_id = "00000000-0000-4000-8000-000000000001"
    contender_observability_id = "00000000-0000-4000-8000-000000000002"

    assert writer.claim_start(
        **arguments,
        claim_token=WRITER_CLAIM_TOKEN,
        observability_id=writer_observability_id,
    )
    assert not contender.claim_start(
        **arguments,
        claim_token=CONTENDER_CLAIM_TOKEN,
        observability_id=contender_observability_id,
    )
    winning_claim = contender.get_start_claim(**arguments)
    assert winning_claim.submission_claim_id == WRITER_CLAIM_TOKEN
    assert winning_claim.observability_id == writer_observability_id
    assert not contender.release_start(
        **arguments,
        claim_token=CONTENDER_CLAIM_TOKEN,
        observability_id=contender_observability_id,
    )
    assert writer.release_start(
        **arguments,
        claim_token=WRITER_CLAIM_TOKEN,
        observability_id=writer_observability_id,
    )
    assert contender.claim_start(
        **arguments,
        claim_token=CONTENDER_CLAIM_TOKEN,
        observability_id=contender_observability_id,
    )


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


def _real_computing_impact(execution_id: str, day: int) -> CachedReformImpact:
    return CachedReformImpact(
        reform_impact_id=reform_impact_id(execution_id),
        baseline_policy_id=1,
        reform_policy_id=2,
        country_id="us",
        region="state/ca",
        dataset="default",
        time_period="2026",
        options_json={},
        options_hash="hash",
        api_version="v1",
        reform_impact_json={},
        status="computing",
        message=None,
        start_time=datetime(2026, 1, day),
        end_time=None,
        execution_id=execution_id,
    )


def test_real_failure_delete_removes_only_the_unchanged_failure(redis_pair) -> None:
    first, second, namespace = redis_pair
    writer = ReformImpactCache(first, namespace)
    deleter = ReformImpactCache(second, namespace)
    identity = ReformImpactIdentity(
        scope=ReformImpactScope(
            country_id="us",
            reform_policy_id=2,
            baseline_policy_id=1,
            region="state/ca",
            dataset="default",
            time_period="2026",
        ),
        api_version="v1",
        options_hash="hash",
    )
    assert writer.set(_real_computing_impact("failed-job", day=1))
    failure = writer.update("failed-job", status="error", message="out of memory")
    newer_job = _real_computing_impact("newer-job", day=2)
    assert writer.set(newer_job)
    # A later poll rewrites the failure after the deleter read it.
    rewritten = writer.update("failed-job", message="out of memory again")

    refused = deleter.delete_failure(failure)
    removed = deleter.delete_failure(rewritten)

    assert refused is False
    assert removed is True
    assert writer.get_by_execution_id("failed-job") is None
    assert writer.matching(identity) == [newer_job]
    assert writer.recent(10) == [newer_job]


def test_real_failure_delete_refuses_a_record_rewritten_before_the_script_runs(
    redis_pair, monkeypatch
) -> None:
    first, second, namespace = redis_pair
    writer = ReformImpactCache(first, namespace)
    deleter = ReformImpactCache(second, namespace)
    assert writer.set(_real_computing_impact("failed-job", day=1))
    failure = writer.update("failed-job", status="error", message="out of memory")
    run_script = second.eval
    rewritten = []

    def rewrite_then_run(script, numkeys, *keys_and_args):
        # Another instance rewrites the record after the deleter read it.
        rewritten.append(writer.update("failed-job", message="out of memory again"))
        return run_script(script, numkeys, *keys_and_args)

    monkeypatch.setattr(second, "eval", rewrite_then_run)

    deleted = deleter.delete_failure(failure)

    assert deleted is False
    assert writer.get_by_execution_id("failed-job") == rewritten[0]
    assert writer.recent(10) == rewritten


def test_real_late_write_never_puts_back_a_deleted_failure(
    redis_pair, monkeypatch
) -> None:
    first, second, namespace = redis_pair
    poller = ReformImpactCache(first, namespace)
    deleter = ReformImpactCache(second, namespace)
    assert poller.set(_real_computing_impact("failed-job", day=1))
    failure = poller.update("failed-job", status="error", message="out of memory")
    write = poller.set

    def delete_then_write(impact, **options):
        # The DELETE runs between the late poll's read and its write.
        assert deleter.delete_failure(failure) is True
        return write(impact, **options)

    monkeypatch.setattr(poller, "set", delete_then_write)

    late_write = poller.update("failed-job", message="out of memory again")

    assert late_write is None
    assert deleter.get_by_execution_id("failed-job") is None
    assert deleter.recent(10) == []
