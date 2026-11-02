"""Budget-window impacts: request limits and the cache identity of a request."""

from dataclasses import replace

import pytest

from policyengine_api.services.budget_window_cache import BudgetWindowCacheState
from policyengine_api.services.economy_service import (
    BUDGET_WINDOW_MAX_END_YEAR,
    BUDGET_WINDOW_MAX_YEARS,
    ImpactStatus,
)
from tests.fixtures.services.economy_service import MOCK_OBSERVABILITY_ID
from tests.fixtures.services.economy_service_helpers import (
    GetBudgetWindowEconomicImpactFixtures,
    complete_budget_window_result,
)

pytest_plugins = ("tests.fixtures.services.economy_service",)
pytestmark = pytest.mark.usefixtures("stable_observability_lifecycle")


class TestEconomyService:
    class TestGetBudgetWindowEconomicImpact(GetBudgetWindowEconomicImpactFixtures):
        def test__given_cliff_target__raises_value_error(
            self, economy_service, base_params
        ):
            base_params["impact_request"] = replace(
                base_params["impact_request"], target="cliff"
            )

            with pytest.raises(
                ValueError,
                match="Budget-window calculations only support target='general'",
            ):
                economy_service.get_budget_window_economic_impact(**base_params)

        def test__given_oversized_window__raises_value_error(
            self, economy_service, base_params
        ):
            base_params["window_size"] = BUDGET_WINDOW_MAX_YEARS + 1

            with pytest.raises(
                ValueError,
                match=(f"window_size must be between 1 and {BUDGET_WINDOW_MAX_YEARS}"),
            ):
                economy_service.get_budget_window_economic_impact(**base_params)

        def test__given_end_year_after_2099__raises_value_error(
            self, economy_service, base_params
        ):
            base_params["start_year"] = "2090"
            base_params["window_size"] = 20

            with pytest.raises(
                ValueError,
                match=(
                    f"budget-window end_year must be {BUDGET_WINDOW_MAX_END_YEAR} "
                    "or earlier"
                ),
            ):
                economy_service.get_budget_window_economic_impact(**base_params)

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_simulation_entrypoint",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_runtime_cache_version__uses_versioned_budget_window_cache_key(
            self,
            economy_service,
            base_params,
            mock_budget_window_cache,
            monkeypatch,
        ):
            cache_version = "e1cache01"

            monkeypatch.setattr(
                "policyengine_api.services.economy_service.get_economy_impact_cache_version",
                lambda _country_id, _api_version=None: cache_version,
            )
            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            cache_key_kwargs = mock_budget_window_cache.build_key.call_args.kwargs
            assert cache_key_kwargs["scope"].time_period == "budget_window:2026:3"
            assert cache_key_kwargs["api_version"] == cache_version

        def test__given_reordered_options__uses_same_budget_window_cache_identity(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            mock_budget_window_cache.get_state.return_value = BudgetWindowCacheState(
                status="completed",
                result=complete_budget_window_result(),
                observability_id=MOCK_OBSERVABILITY_ID,
            )

            economy_service.get_budget_window_economic_impact(
                **{
                    **base_params,
                    "impact_request": replace(
                        base_params["impact_request"],
                        options={"staging_probe": "abc", "analysis_mode": "x"},
                    ),
                }
            )
            first_cache_key_kwargs = dict(
                mock_budget_window_cache.build_key.call_args.kwargs
            )
            mock_budget_window_cache.build_key.reset_mock()

            economy_service.get_budget_window_economic_impact(
                **{
                    **base_params,
                    "impact_request": replace(
                        base_params["impact_request"],
                        options={"analysis_mode": "x", "staging_probe": "abc"},
                    ),
                }
            )
            second_cache_key_kwargs = dict(
                mock_budget_window_cache.build_key.call_args.kwargs
            )

            assert first_cache_key_kwargs == second_cache_key_kwargs
            mock_simulation_entrypoint.run_budget_window_batch.assert_not_called()

        @pytest.mark.usefixtures(
            "mock_reform_impacts_service", "mock_simulation_entrypoint"
        )
        def test__given_legacy_us_region__normalizes_before_building_cache_key(
            self,
            economy_service,
            base_params,
            mock_budget_window_cache,
        ):
            base_params["impact_request"] = replace(
                base_params["impact_request"], region="ca", dataset="default"
            )

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            assert mock_budget_window_cache.build_key.call_args.kwargs[
                "scope"
            ].region == ("state/ca")
