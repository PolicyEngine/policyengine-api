"""Characterization of how household calculation options reach the country model."""

from copy import deepcopy
from typing import ClassVar

import pytest

from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.household_calculations import (
    HouseholdCalculationCache,
)
from policyengine_api.services import household_calculation_service
from policyengine_api.services.household_calculation_service import (
    CalculationResult,
    HouseholdCalculationResult,
    HouseholdCalculationService,
    PreparedHouseholdCalculation,
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


class RecordingCountry:
    """A country model that records each calculation request it receives."""

    metadata: ClassVar[dict] = {
        "variables": {
            "age": {
                "name": "age",
                "entity": "person",
                "definitionPeriod": "year",
                "defaultValue": 0,
                "isInputVariable": True,
            },
            "income_tax": {
                "name": "income_tax",
                "entity": "person",
                "definitionPeriod": "year",
                "defaultValue": 0,
                "isInputVariable": False,
            },
            "pay_period_income": {
                "name": "pay_period_income",
                "entity": "person",
                "definitionPeriod": "month",
                "defaultValue": 12.5,
                "isInputVariable": True,
            },
            "daily_hours": {
                "name": "daily_hours",
                "entity": "person",
                "definitionPeriod": "day",
                "defaultValue": 8,
                "isInputVariable": True,
            },
        },
        "entities": {"person": {"plural": "people", "roles": {}}},
        "parameters": {},
    }

    def __init__(self) -> None:
        self.requests: list[tuple[dict, dict, dict]] = []

    def calculate(self, household, policy, **options):
        self.requests.append((deepcopy(household), deepcopy(policy), options))
        receipt = SPM_RECEIPT if options.get("spm") is not None else None
        return CalculationResult(
            household={"calculated": household},
            warnings=("calculated with a fallback",),
            spm_provenance=receipt,
        )


@pytest.fixture
def country(monkeypatch):
    monkeypatch.setattr(
        household_calculation_service,
        "normalize_spm_selection",
        lambda country_id, selection: None if selection is None else dict(selection),
    )
    return RecordingCountry()


@pytest.fixture
def service(country):
    return HouseholdCalculationService(
        cache=HouseholdCalculationCache(
            InMemoryCacheBackend(), CacheNamespace("test", "api")
        ),
        country_provider=lambda: {"us": country},
    )


def test_default_calculation_sends_the_household_unchanged(service, country):
    result = service.calculate_household("us", deepcopy(HOUSEHOLD), {})

    assert country.requests == [(HOUSEHOLD, {}, {})]
    assert result == HouseholdCalculationResult(
        household={"calculated": HOUSEHOLD},
        warnings=("calculated with a fallback",),
    )


def test_add_missing_fills_yearly_and_monthly_variables(service, country):
    service.calculate_household("us", deepcopy(HOUSEHOLD), {}, add_missing=True)

    assert country.requests == [
        (
            {
                "people": {
                    "you": {
                        "age": {"2026": 40},
                        "income_tax": {"2026": None},
                        "pay_period_income": {"2026": 12.5},
                    }
                }
            },
            {},
            {},
        )
    ]


@pytest.mark.parametrize("spm_requested", [True, False])
def test_spm_selection_and_request_flag_reach_the_country(
    service, country, spm_requested
):
    result = service.calculate_household(
        "us",
        deepcopy(HOUSEHOLD),
        {},
        spm=SPM_CONFIG,
        spm_requested=spm_requested,
    )

    assert country.requests == [
        (HOUSEHOLD, {}, {"spm": SPM_CONFIG, "spm_requested": spm_requested})
    ]
    assert result.spm_provenance == SPM_RECEIPT


def test_prepared_calculation_keeps_every_option(service, country):
    prepared = service.prepare_household_calculation(
        "us",
        deepcopy(HOUSEHOLD),
        {},
        add_missing=True,
        spm=SPM_CONFIG,
        spm_requested=True,
    )

    assert prepared == PreparedHouseholdCalculation(
        country=country,
        household_json={
            "people": {
                "you": {
                    "age": {"2026": 40},
                    "income_tax": {"2026": None},
                    "pay_period_income": {"2026": 12.5},
                }
            }
        },
        policy_json={},
        spm=SPM_CONFIG,
        spm_requested=True,
        warnings=(),
    )
    assert country.requests == []


def test_preparing_does_not_change_the_callers_household(service):
    household = deepcopy(HOUSEHOLD)

    service.prepare_household_calculation("us", household, {}, add_missing=True)

    assert household == HOUSEHOLD
