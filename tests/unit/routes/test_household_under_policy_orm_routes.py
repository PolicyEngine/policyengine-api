"""ORM integration behavior for the household-under-policy route."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS, POLICYENGINE_VERSION
from policyengine_api.data.v1_models import (
    Household,
    Policy,
)
from policyengine_api.routes.household_routes import get_household_under_policy
from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.household_calculations import (
    CachedHouseholdCalculation,
    HouseholdCalculationCache,
    HouseholdCalculationIdentity,
)
from policyengine_api.services.household_calculation_service import (
    CalculationResult,
    HouseholdCalculationService,
)
from tests.fixtures.spm import INSTALLED_SPM_SELECTION, household_result_fields


def test_household_under_policy_returns_cached_json_object(orm_session_factory):
    stored_result = {"people": {"you": {"net_income": {"2026": 42}}}}
    with orm_session_factory.begin() as session:
        session.add_all(
            [
                Household(
                    id=1,
                    country_id="us",
                    label=None,
                    api_version=COUNTRY_PACKAGE_VERSIONS["us"],
                    household_json={},
                    household_hash="household-hash",
                ),
                Policy(
                    id=2,
                    country_id="us",
                    label=None,
                    api_version=COUNTRY_PACKAGE_VERSIONS["us"],
                    policy_json={},
                    policy_hash="policy-hash",
                ),
            ]
        )
    cache = HouseholdCalculationCache(
        InMemoryCacheBackend(),
        CacheNamespace("test", "api"),
    )
    cache.set(
        HouseholdCalculationIdentity(
            country_id="us",
            household_id=1,
            policy_id=2,
            household_hash="household-hash",
            policy_hash="policy-hash",
            country_package_version=COUNTRY_PACKAGE_VERSIONS["us"],
            policyengine_version=POLICYENGINE_VERSION,
            spm=INSTALLED_SPM_SELECTION,
        ),
        CachedHouseholdCalculation(
            household=stored_result,
            **household_result_fields(years=["2026"]),
        ),
    )
    service = HouseholdCalculationService(
        primary_session_factory=orm_session_factory,
        cache=cache,
    )

    with patch(
        "policyengine_api.routes.household_routes.household_calculation_service",
        service,
    ):
        response = get_household_under_policy("us", "1", "2")

    assert response["result"] == {"people": {"you": {"net_income": {"2026": 42}}}}


def test_household_under_policy_calculates_and_caches_json_as_an_object(
    orm_session_factory,
):
    with orm_session_factory.begin() as session:
        session.add_all(
            [
                Household(
                    id=1,
                    country_id="us",
                    label=None,
                    api_version=COUNTRY_PACKAGE_VERSIONS["us"],
                    household_json={"people": {"you": {}}},
                    household_hash="household-hash",
                ),
                Policy(
                    id=2,
                    country_id="us",
                    label=None,
                    api_version=COUNTRY_PACKAGE_VERSIONS["us"],
                    policy_json={"gov.example.parameter": 1},
                    policy_hash="policy-hash",
                ),
            ]
        )
    calculated = {"people": {"you": {"net_income": {"2026": 42}}}}
    country = SimpleNamespace(
        calculate=Mock(
            return_value=CalculationResult(
                household=calculated,
                **household_result_fields(years=["2026"]),
            )
        ),
        metadata={
            "variables": {},
            "entities": {"person": {"plural": "people", "roles": {}}},
            "parameters": {"gov.example.parameter": {"type": "parameter"}},
        },
    )
    service = HouseholdCalculationService(
        primary_session_factory=orm_session_factory,
        cache=HouseholdCalculationCache(
            InMemoryCacheBackend(),
            CacheNamespace("test", "api"),
        ),
        country_provider=lambda: {"us": country},
    )

    with patch(
        "policyengine_api.routes.household_routes.household_calculation_service",
        service,
    ):
        response = get_household_under_policy("us", "1", "2")

    assert response["result"] == calculated
    country.calculate.assert_called_once_with(
        {"people": {"you": {}}},
        {"gov.example.parameter": 1},
        spm=INSTALLED_SPM_SELECTION,
        spm_requested=False,
    )
