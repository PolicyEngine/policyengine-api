"""Characterization of how a calculated-household cache read treats each entry."""

import pytest

from policyengine_api.runtime_cache.core import CacheNamespace, encode_envelope
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.household_calculations import (
    HOUSEHOLD_CALCULATION_SCHEMA_VERSION,
    CachedHouseholdCalculation,
    HouseholdCalculationCache,
    HouseholdCalculationIdentity,
)

SPM_CONFIG = {
    "forecast_content_sha256": "a" * 64,
    "scenario": "baseline",
    "geography_kind": "national",
    "geography_id": None,
    "county_vintage": "2020",
    "as_of": None,
}
SPM_RECEIPT = {
    "schema_version": "canonical-spm-provenance-v2",
    "forecast_id": "test-artifact",
    "forecast_sha256": "a" * 64,
    "scenario": "baseline",
    "geography_kind": "national",
    "geography_id": None,
    "county_vintage": "2020",
    "as_of": None,
    "runtime_versions": {
        "policyengine": "test",
        "policyengine-core": "test",
        "policyengine-us": "test",
        "spm-calculator": "test",
    },
    "years": ["2026"],
}
HOUSEHOLD = {"people": {"you": {"age": {"2026": 40}}}}


def _identity(spm: dict | None) -> HouseholdCalculationIdentity:
    return HouseholdCalculationIdentity(
        country_id="us",
        household_id=1,
        policy_id=2,
        household_hash="household-a",
        policy_hash="policy-a",
        country_package_version="1.2.3",
        policyengine_version="4.5.6",
        spm=spm,
    )


def _read_stored(payload: object, spm: dict | None) -> object:
    backend = InMemoryCacheBackend()
    cache = HouseholdCalculationCache(backend, CacheNamespace("test", "api"))
    identity = _identity(spm)
    backend.set(
        cache.cache_key(identity),
        encode_envelope(
            "household-calculation",
            HOUSEHOLD_CALCULATION_SCHEMA_VERSION,
            payload,
        ),
    )
    return cache.get(identity)


@pytest.mark.parametrize(
    ("payload", "spm"),
    [
        pytest.param(["not", "an", "object"], None, id="payload-not-object"),
        pytest.param({"household": [], "warnings": []}, None, id="household-list"),
        pytest.param({"household": HOUSEHOLD, "warnings": "x"}, None, id="warnings"),
        pytest.param({"household": HOUSEHOLD}, None, id="warnings-missing"),
        pytest.param(
            {"household": HOUSEHOLD, "warnings": ["ok", 3]}, None, id="warning-int"
        ),
        pytest.param(
            {"household": HOUSEHOLD, "warnings": [], "spm_config": SPM_CONFIG},
            None,
            id="legacy-spm-config",
        ),
        pytest.param(
            {"household": HOUSEHOLD, "warnings": [], "spm_provenance": "receipt"},
            None,
            id="receipt-not-object",
        ),
        pytest.param(
            {"household": HOUSEHOLD, "warnings": [], "spm_provenance": SPM_RECEIPT},
            None,
            id="receipt-without-requested-spm",
        ),
        pytest.param(
            {"household": HOUSEHOLD, "warnings": []}, SPM_CONFIG, id="receipt-missing"
        ),
        pytest.param(
            {
                "household": HOUSEHOLD,
                "warnings": [],
                "spm_provenance": {**SPM_RECEIPT, "years": "2026"},
            },
            SPM_CONFIG,
            id="receipt-invalid",
        ),
        pytest.param(
            {"household": HOUSEHOLD, "warnings": [], "spm_provenance": SPM_RECEIPT},
            {**SPM_CONFIG, "scenario": "other"},
            id="receipt-for-other-selection",
        ),
    ],
)
def test_malformed_or_mismatched_entries_read_as_misses(payload, spm):
    assert _read_stored(payload, spm) is None


def test_entry_without_spm_reads_back_with_warnings_as_a_tuple():
    cached = _read_stored(
        {"household": HOUSEHOLD, "warnings": ["first", "second"]},
        None,
    )

    assert cached == CachedHouseholdCalculation(
        household=HOUSEHOLD,
        warnings=("first", "second"),
        spm_provenance=None,
    )


def test_entry_with_explicit_null_receipt_and_no_spm_is_a_hit():
    cached = _read_stored(
        {"household": HOUSEHOLD, "warnings": [], "spm_provenance": None},
        None,
    )

    assert cached == CachedHouseholdCalculation(household=HOUSEHOLD)


def test_matching_receipt_reads_back_in_its_canonical_form():
    cached = _read_stored(
        {"household": HOUSEHOLD, "warnings": ["w"], "spm_provenance": SPM_RECEIPT},
        SPM_CONFIG,
    )

    assert cached == CachedHouseholdCalculation(
        household=HOUSEHOLD,
        warnings=("w",),
        spm_provenance=SPM_RECEIPT,
    )
