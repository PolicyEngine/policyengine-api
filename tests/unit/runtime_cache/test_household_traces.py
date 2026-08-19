"""Computed-household and tracer cache tests."""

from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.household_traces import (
    HouseholdTraceCache,
    HouseholdTraceIdentity,
    HouseholdTraceValue,
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
