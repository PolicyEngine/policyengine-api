"""Calculated-household result cache tests."""

import pytest

from policyengine_api.runtime_cache.core import CacheNamespace, encode_envelope
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.household_calculations import (
    HOUSEHOLD_CALCULATION_SCHEMA_VERSION,
    CachedHouseholdCalculation,
    HouseholdCalculationCache,
    HouseholdCalculationIdentity,
)


def _namespace() -> CacheNamespace:
    return CacheNamespace("test", "api")


def _identity(**changes) -> HouseholdCalculationIdentity:
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
    return HouseholdCalculationIdentity(**values)


def test_household_and_warnings_share_one_atomic_versioned_value() -> None:
    backend = InMemoryCacheBackend()
    cache = HouseholdCalculationCache(backend, _namespace())
    value = CachedHouseholdCalculation(
        household={"people": {"you": {"income": {"2026": 42}}}},
        warnings=("income calculation used a fallback value",),
    )
    identity = _identity()

    assert cache.set(identity, value) is True
    assert cache.get(identity) == value
    assert list(backend._values) == [cache.cache_key(identity)]
    assert "tracer" not in backend._values[cache.cache_key(identity)]
    assert cache.cache_key(identity) != cache.cache_key(
        _identity(household_hash="household-b")
    )
    assert cache.cache_key(identity) != cache.cache_key(
        _identity(country_package_version="9.9.9")
    )


def test_selection_participates_in_cache_identity() -> None:
    cache = HouseholdCalculationCache(InMemoryCacheBackend(), _namespace())

    assert cache.cache_key(_identity()) != cache.cache_key(
        _identity(spm={"geography_kind": "national"})
    )
    assert cache.cache_key(_identity(spm={"geography_kind": "national"})) != (
        cache.cache_key(_identity(spm={"geography_kind": "county"}))
    )


def test_receipt_bearing_payload_supersedes_the_receiptless_schema() -> None:
    """Entries written before the selection joined this family are misses."""
    backend = InMemoryCacheBackend()
    cache = HouseholdCalculationCache(backend, _namespace())
    identity = _identity()
    previous_version = HOUSEHOLD_CALCULATION_SCHEMA_VERSION - 1
    backend.set(
        _namespace().key(
            "household-calculation",
            previous_version,
            {name: value for name, value in vars(identity).items() if name != "spm"},
        ),
        encode_envelope(
            "household-calculation",
            previous_version,
            {"household": {"people": {}}, "warnings": []},
        ),
    )

    assert cache.get(identity) is None


SPM_CONFIG = {
    "forecast_content_sha256": "a" * 64,
    "scenario": "baseline",
    "geography_kind": "national",
    "geography_id": None,
    "county_vintage": "2020",
    "as_of": None,
}
SPM_RECEIPT = {
    "forecast_id": "test-artifact",
    "forecast_sha256": "a" * 64,
    "scenario": "baseline",
    "geography_kind": "national",
    "runtime_versions": {"policyengine-us": "test"},
    "years": {},
    "geographies": [],
    "composition_method": "test composition",
    "storage_method": "test storage",
}


@pytest.mark.parametrize(
    "receipt",
    [
        {},
        {**SPM_RECEIPT, "forecast_sha256": "b" * 64},
        {**SPM_RECEIPT, "scenario": "other"},
        {**SPM_RECEIPT, "geography_kind": "county"},
        {**SPM_RECEIPT, "years": []},
        {**SPM_RECEIPT, "unexpected": True},
    ],
    ids=["empty", "hash", "scenario", "geography", "years-shape", "unknown-field"],
)
def test_household_cache_rejects_invalid_or_mismatched_spm_receipts(receipt):
    cache = HouseholdCalculationCache(InMemoryCacheBackend(), _namespace())
    identity = _identity(spm=SPM_CONFIG)
    value = CachedHouseholdCalculation(
        household={"people": {}},
        spm_config=SPM_CONFIG,
        spm_provenance=receipt,
    )
    assert cache.set(identity, value) is True
    assert cache.get(identity) is None


@pytest.mark.parametrize("years", [{}, {"2024": {"source": "test"}}])
def test_household_cache_keeps_valid_receipts_including_lazy_tax_only(years):
    cache = HouseholdCalculationCache(InMemoryCacheBackend(), _namespace())
    identity = _identity(spm=SPM_CONFIG)
    value = CachedHouseholdCalculation(
        household={"people": {}},
        spm_config=SPM_CONFIG,
        spm_provenance={**SPM_RECEIPT, "years": years},
    )
    assert cache.set(identity, value) is True
    assert cache.get(identity) == value


@pytest.mark.parametrize("calculate_spm", [False, True], ids=["tax-only", "measured"])
def test_real_country_provider_receipt_round_trips_household_cache(calculate_spm):
    country_spm = pytest.importorskip("policyengine_us.spm")
    provider = country_spm.create_spm_provider({"geography_kind": "national"})
    if calculate_spm:
        provider.calculate_unit(
            year=provider.forecast.years[0],
            adults=1,
            children=0,
            tenure="renter",
        )
    config = country_spm.spm_config(provider)
    receipt = provider.provenance()
    assert bool(receipt["years"]) is calculate_spm

    cache = HouseholdCalculationCache(InMemoryCacheBackend(), _namespace())
    identity = _identity(spm=config)
    value = CachedHouseholdCalculation(
        household={"people": {}},
        spm_config=config,
        spm_provenance=receipt,
    )
    assert cache.set(identity, value) is True
    assert cache.get(identity) == value


OMITTED_NULL_CONFIG = {
    key: value for key, value in SPM_CONFIG.items() if value is not None
}


def test_household_cache_hits_when_receipt_omits_null_settings():
    """A canonical receipt may omit its null values; that is still the same selection."""
    cache = HouseholdCalculationCache(InMemoryCacheBackend(), _namespace())
    identity = _identity(spm=SPM_CONFIG)
    value = CachedHouseholdCalculation(
        household={"people": {}},
        spm_config=OMITTED_NULL_CONFIG,
        spm_provenance=SPM_RECEIPT,
    )
    assert cache.set(identity, value) is True
    assert cache.get(identity) == value


@pytest.mark.parametrize("omitted", sorted(OMITTED_NULL_CONFIG))
def test_household_cache_rejects_receipt_omitting_a_nonnull_setting(omitted):
    """An omitted non-null setting must never inherit today's resolved default."""
    cache = HouseholdCalculationCache(InMemoryCacheBackend(), _namespace())
    identity = _identity(spm=SPM_CONFIG)
    value = CachedHouseholdCalculation(
        household={"people": {}},
        spm_config={
            key: item for key, item in OMITTED_NULL_CONFIG.items() if key != omitted
        },
        spm_provenance=SPM_RECEIPT,
    )
    assert cache.set(identity, value) is True
    assert cache.get(identity) is None


@pytest.mark.parametrize(
    "changed",
    [
        {"geography_kind": "county"},
        {"scenario": "other"},
        {"county_vintage": "2010"},
        {"geography_id": "31080"},
        {"as_of": "2026-09-09"},
        {"unexpected": True},
    ],
)
def test_household_cache_rejects_receipt_with_different_settings(changed):
    cache = HouseholdCalculationCache(InMemoryCacheBackend(), _namespace())
    identity = _identity(spm=SPM_CONFIG)
    value = CachedHouseholdCalculation(
        household={"people": {}},
        spm_config={**OMITTED_NULL_CONFIG, **changed},
        spm_provenance=SPM_RECEIPT,
    )
    assert cache.set(identity, value) is True
    assert cache.get(identity) is None
