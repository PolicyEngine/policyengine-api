"""Helpers and shared class fixtures for the economy service tests."""

from typing import Literal, NamedTuple
from unittest.mock import MagicMock

import httpx
import pytest

from policyengine_api.services.economic_impact_request import EconomicImpactRequest
from policyengine_api.services.economy_service import (
    EconomicImpactSetupOptions,
    EconomyService,
)
from tests.fixtures.services.economy_service import (
    MOCK_API_VERSION,
    MOCK_BASELINE_POLICY_ID,
    MOCK_COUNTRY_ID,
    MOCK_DATASET,
    MOCK_OPTIONS,
    MOCK_POLICY_ID,
    MOCK_REGION,
    MOCK_SUBMISSION_CLAIM_ID,
    MOCK_TIME_PERIOD,
)
from tests.fixtures.spm import worker_result_fields


def setup_options_for(country_id: str, region: str) -> EconomicImpactSetupOptions:
    """Return resolved setup options for one country and pre-normalized region."""
    return EconomicImpactSetupOptions(
        submission_claim_id=MOCK_SUBMISSION_CLAIM_ID,
        country_id=country_id,
        reform_policy_id=MOCK_POLICY_ID,
        baseline_policy_id=MOCK_BASELINE_POLICY_ID,
        region=region,
        dataset=MOCK_DATASET,
        time_period=MOCK_TIME_PERIOD,
        options={},
        api_version=MOCK_API_VERSION,
        target="general",
    )


def uk_breakdown_request(
    *,
    country_id: str = "uk",
    region: str = "uk",
    target: Literal["general", "cliff"] = "general",
) -> EconomicImpactRequest:
    """Return an annual request for the UK local-area breakdown."""
    return EconomicImpactRequest(
        country_id=country_id,
        policy_id=MOCK_POLICY_ID,
        baseline_policy_id=MOCK_BASELINE_POLICY_ID,
        region=region,
        dataset="default",
        options={"breakdown": "local_areas"},
        api_version=MOCK_API_VERSION,
        target=target,
    )


class EconomyServiceHarness(NamedTuple):
    """The service under test, its call parameters and the mocks it talks to."""

    service: EconomyService
    params: dict
    reform_impacts_service: MagicMock
    simulation_entrypoint: MagicMock


def hash_prefix_lookup(reform_impacts_service: MagicMock) -> MagicMock:
    """Return the mocked lookup of reform impacts by options-hash prefix."""
    lookup: MagicMock = (
        reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix
    )
    return lookup


def make_mock_budget_impact_data(
    *,
    tax_revenue_impact: int,
    state_tax_revenue_impact: int,
    benefit_spending_impact: int,
    budgetary_impact: int,
):
    return {
        "budget": {
            "tax_revenue_impact": tax_revenue_impact,
            "state_tax_revenue_impact": state_tax_revenue_impact,
            "benefit_spending_impact": benefit_spending_impact,
            "budgetary_impact": budgetary_impact,
        }
    }


def make_http_status_error(
    status_code: int,
    payload: dict | None = None,
    text: str | None = None,
) -> httpx.HTTPStatusError:
    request = httpx.Request(
        "POST",
        "https://policyengine-staging--policyengine-simulation-gateway-web-app.modal.run/simulate/economy/budget-window",
    )
    response = (
        httpx.Response(status_code, json=payload, request=request)
        if payload is not None
        else httpx.Response(status_code, text=text or "", request=request)
    )
    return httpx.HTTPStatusError(
        f"Client error '{status_code}'",
        request=request,
        response=response,
    )


def complete_budget_window_result(
    *, annual_values: dict[str, dict] | None = None, totals: dict | None = None
) -> dict:
    years = ("2026", "2027", "2028")
    annual_values = annual_values or {}
    return {
        "kind": "budgetWindow",
        "startYear": years[0],
        "endYear": years[-1],
        "windowSize": len(years),
        "annualImpacts": [
            {
                "year": year,
                **annual_values.get(year, {}),
                **worker_result_fields(years=[year]),
            }
            for year in years
        ],
        "totals": totals or {},
    }


class GetEconomicImpactFixtures:
    """Fixtures shared by the TestGetEconomicImpact classes in several files."""

    @pytest.fixture
    def economy_service(self):
        return EconomyService()

    @pytest.fixture
    def base_params(self):
        return {
            "impact_request": EconomicImpactRequest(
                country_id=MOCK_COUNTRY_ID,
                policy_id=MOCK_POLICY_ID,
                baseline_policy_id=MOCK_BASELINE_POLICY_ID,
                region=MOCK_REGION,
                dataset=MOCK_DATASET,
                options=MOCK_OPTIONS,
                api_version=MOCK_API_VERSION,
                target="general",
            ),
            "time_period": MOCK_TIME_PERIOD,
        }

    @pytest.fixture
    def economy_service_harness(
        self,
        economy_service: EconomyService,
        base_params: dict,
        mock_reform_impacts_service: MagicMock,
        mock_simulation_entrypoint: MagicMock,
    ) -> EconomyServiceHarness:
        return EconomyServiceHarness(
            service=economy_service,
            params=base_params,
            reform_impacts_service=mock_reform_impacts_service,
            simulation_entrypoint=mock_simulation_entrypoint,
        )


class GetBudgetWindowEconomicImpactFixtures:
    """Fixtures shared by the TestGetBudgetWindowEconomicImpact classes."""

    @pytest.fixture
    def economy_service(
        self,
        mock_country_package_versions,
        mock_policy_service,
        mock_logger,
        mock_datetime,
        mock_submission_claim_id,
    ):
        return EconomyService()

    @pytest.fixture
    def base_params(self):
        return {
            "impact_request": EconomicImpactRequest(
                country_id=MOCK_COUNTRY_ID,
                policy_id=MOCK_POLICY_ID,
                baseline_policy_id=MOCK_BASELINE_POLICY_ID,
                region=MOCK_REGION,
                dataset=MOCK_DATASET,
                options=MOCK_OPTIONS,
                api_version=MOCK_API_VERSION,
                target="general",
            ),
            "start_year": "2026",
            "window_size": 3,
        }
