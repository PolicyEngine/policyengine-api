"""Budget-window impacts answered from stored state or a polled batch job."""

from unittest.mock import patch

import httpx
import pytest

from policyengine_api.services.budget_window_cache import BudgetWindowCacheState
from policyengine_api.services.economy_service import (
    BudgetWindowYearProgress,
    ImpactStatus,
)
from policyengine_api.spm import SPMValidationError
from tests.fixtures.services.economy_service import (
    MOCK_OBSERVABILITY_ID,
    MockBatchProgress,
    create_mock_budget_window_batch_execution,
)
from tests.fixtures.services.economy_service_helpers import (
    GetBudgetWindowEconomicImpactFixtures,
    complete_budget_window_result,
    make_http_status_error,
)

pytest_plugins = ("tests.fixtures.services.economy_service",)
pytestmark = pytest.mark.usefixtures("stable_observability_lifecycle")


class TestEconomyService:
    class TestGetBudgetWindowEconomicImpact(GetBudgetWindowEconomicImpactFixtures):
        def test__given_completed_cached_result__returns_completed_batch_result(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            completed_result = complete_budget_window_result(
                annual_values={
                    "2026": {
                        "year": "2026",
                        "taxRevenueImpact": 100,
                        "federalTaxRevenueImpact": 80,
                        "stateTaxRevenueImpact": 20,
                        "benefitSpendingImpact": -10,
                        "budgetaryImpact": 90,
                    },
                },
                totals={
                    "year": "Total",
                    "taxRevenueImpact": 100,
                    "federalTaxRevenueImpact": 80,
                    "stateTaxRevenueImpact": 20,
                    "benefitSpendingImpact": -10,
                    "budgetaryImpact": 90,
                },
            )
            mock_budget_window_cache.get_state.return_value = BudgetWindowCacheState(
                status="completed",
                result=completed_result,
                observability_id=MOCK_OBSERVABILITY_ID,
            )

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.OK
            assert result.progress == 100
            assert result.data == completed_result
            assert result.cache_status == "result-hit"
            mock_simulation_entrypoint.get_budget_window_batch_by_id.assert_not_called()
            mock_simulation_entrypoint.run_budget_window_batch.assert_not_called()

        def test__given_cached_batch_id__returns_running_batch_progress(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            mock_budget_window_cache.get_state.return_value = BudgetWindowCacheState(
                status="submitted",
                batch_job_id="fc-budget-123",
                observability_id=MOCK_OBSERVABILITY_ID,
            )
            mock_simulation_entrypoint.get_budget_window_batch_by_id.return_value = (
                create_mock_budget_window_batch_execution(
                    batch_job_id="fc-budget-123",
                    status="running",
                    batch_progress=MockBatchProgress(
                        progress=33,
                        completed_years=["2026"],
                        running_years=["2027"],
                        queued_years=["2028"],
                    ),
                )
            )

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            assert result.progress == 33
            assert result.completed_years == ["2026"]
            assert result.computing_years == ["2027"]
            assert result.queued_years == ["2028"]
            assert result.cache_status == "batch-id-hit"
            assert "1 of 3 complete" in result.message
            mock_simulation_entrypoint.get_budget_window_batch_by_id.assert_called_once_with(
                "fc-budget-123"
            )

        def test__given_completed_batch_poll__caches_result_and_returns_completed(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            completed_result = complete_budget_window_result()
            mock_budget_window_cache.get_state.return_value = BudgetWindowCacheState(
                status="submitted",
                batch_job_id="fc-budget-123",
                observability_id=MOCK_OBSERVABILITY_ID,
            )
            mock_simulation_entrypoint.get_budget_window_batch_by_id.return_value = (
                create_mock_budget_window_batch_execution(
                    batch_job_id="fc-budget-123",
                    status="complete",
                    batch_progress=MockBatchProgress(
                        progress=100, completed_years=["2026", "2027", "2028"]
                    ),
                    result=completed_result,
                )
            )

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.OK
            assert result.data == completed_result
            assert result.cache_status == "batch-id-hit"
            mock_budget_window_cache.set_completed_result.assert_called_once_with(
                "budget-window-cache-key",
                completed_result,
                MOCK_OBSERVABILITY_ID,
            )

        @pytest.mark.parametrize("malformed_result", [None, {}, []])
        def test__given_completed_batch_without_result__returns_error_without_caching(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
            malformed_result,
        ):
            mock_budget_window_cache.get_state.return_value = BudgetWindowCacheState(
                status="submitted",
                batch_job_id="fc-budget-123",
                observability_id=MOCK_OBSERVABILITY_ID,
            )
            mock_simulation_entrypoint.get_budget_window_batch_by_id.return_value = (
                create_mock_budget_window_batch_execution(
                    batch_job_id="fc-budget-123",
                    status="complete",
                    batch_progress=MockBatchProgress(
                        progress=100,
                        completed_years=["2026", "2027"],
                        running_years=[],
                        queued_years=["2028"],
                    ),
                    result=malformed_result,
                )
            )

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.ERROR
            assert result.error == "Budget-window batch completed without a result"
            assert result.completed_years == ["2026", "2027"]
            assert result.computing_years == []
            assert result.queued_years == ["2028"]
            assert result.cache_status == "batch-id-hit"
            mock_budget_window_cache.set_completed_result.assert_not_called()
            mock_budget_window_cache.set_execution_failure.assert_called_once()

        def test__given_completed_batch_cache_write_fails__does_not_clear_batch_id(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            completed_result = complete_budget_window_result()
            mock_budget_window_cache.get_state.return_value = BudgetWindowCacheState(
                status="submitted",
                batch_job_id="fc-budget-123",
                observability_id=MOCK_OBSERVABILITY_ID,
            )
            mock_budget_window_cache.set_completed_result.return_value = False
            mock_simulation_entrypoint.get_budget_window_batch_by_id.return_value = (
                create_mock_budget_window_batch_execution(
                    batch_job_id="fc-budget-123",
                    status="complete",
                    batch_progress=MockBatchProgress(
                        progress=100, completed_years=["2026", "2027", "2028"]
                    ),
                    result=completed_result,
                )
            )

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.OK
            assert result.data == completed_result
            mock_budget_window_cache.set_completed_result.assert_called_once_with(
                "budget-window-cache-key",
                completed_result,
                MOCK_OBSERVABILITY_ID,
            )

        def test__given_failed_batch_poll__returns_failed(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            mock_budget_window_cache.get_state.return_value = BudgetWindowCacheState(
                status="submitted",
                batch_job_id="fc-budget-123",
                observability_id=MOCK_OBSERVABILITY_ID,
            )
            mock_simulation_entrypoint.get_budget_window_batch_by_id.return_value = (
                create_mock_budget_window_batch_execution(
                    batch_job_id="fc-budget-123",
                    status="failed",
                    batch_progress=MockBatchProgress(
                        progress=33,
                        completed_years=["2026"],
                        queued_years=["2028"],
                        failed_years=["2027"],
                    ),
                    error="Budget window failed for 2027",
                )
            )

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.ERROR
            assert result.error == "Budget window failed for 2027"
            assert result.completed_years == ["2026"]
            assert result.computing_years == []
            assert result.queued_years == ["2028"]
            assert result.cache_status == "batch-id-hit"
            mock_budget_window_cache.set_completed_result.assert_not_called()
            mock_budget_window_cache.set_execution_failure.assert_called_once()

        def test_typed_error_write_failure_retains_batch_identity(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            error = SPMValidationError("SPM_YEAR_UNAVAILABLE", "No forecast for 2036")
            mock_budget_window_cache.get_state.return_value = BudgetWindowCacheState(
                status="submitted",
                batch_job_id="expired-job",
                observability_id=MOCK_OBSERVABILITY_ID,
            )
            mock_budget_window_cache.set_terminal_error.return_value = False
            mock_simulation_entrypoint.get_budget_window_batch_by_id.side_effect = error

            with pytest.raises(SPMValidationError) as raised:
                economy_service.get_budget_window_economic_impact(**base_params)

            assert raised.value is error
            mock_budget_window_cache.set_completed_result.assert_not_called()
            mock_simulation_entrypoint.run_budget_window_batch.assert_not_called()

        def test_untyped_poll_error_keeps_existing_retry_behavior(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            error = make_http_status_error(422, payload={"detail": "Unknown error"})
            mock_budget_window_cache.get_state.return_value = BudgetWindowCacheState(
                status="submitted",
                batch_job_id="existing-job",
                observability_id=MOCK_OBSERVABILITY_ID,
            )
            mock_simulation_entrypoint.get_budget_window_batch_by_id.side_effect = error

            with pytest.raises(httpx.HTTPStatusError) as raised:
                economy_service.get_budget_window_economic_impact(**base_params)

            assert raised.value is error
            mock_budget_window_cache.set_terminal_error.assert_not_called()
            mock_simulation_entrypoint.run_budget_window_batch.assert_not_called()

        def test__given_cached_execution_failure__replays_failure_and_identity(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            stored_observability_id = "00000000-0000-4000-8000-000000000099"
            mock_budget_window_cache.get_state.return_value = BudgetWindowCacheState(
                status="failed",
                observability_id=stored_observability_id,
                failure_type="execution",
                error={
                    "status": "error",
                    "error": "Budget window failed for 2027",
                    "completed_years": ["2026"],
                    "queued_years": ["2028"],
                },
            )

            with patch(
                "policyengine_api.services.economy_budget_window_submission.restore_observability_id",
                return_value=stored_observability_id,
            ) as restore_observability_id:
                result = economy_service.get_budget_window_economic_impact(
                    **base_params
                )

            assert result.status == ImpactStatus.ERROR
            assert result.error == "Budget window failed for 2027"
            assert result.cache_status == "failure-hit"
            restore_observability_id.assert_called_with(stored_observability_id)
            mock_simulation_entrypoint.get_budget_window_batch_by_id.assert_not_called()
            mock_simulation_entrypoint.run_budget_window_batch.assert_not_called()

        def test__given_unexpected_batch_status__raises_value_error(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            mock_budget_window_cache.get_state.return_value = BudgetWindowCacheState(
                status="submitted",
                batch_job_id="fc-budget-123",
                observability_id=MOCK_OBSERVABILITY_ID,
            )
            mock_simulation_entrypoint.get_budget_window_batch_by_id.return_value = (
                create_mock_budget_window_batch_execution(
                    batch_job_id="fc-budget-123",
                    status="paused",
                )
            )

            with pytest.raises(
                ValueError,
                match="Unexpected budget-window batch execution state: paused",
            ):
                economy_service.get_budget_window_economic_impact(**base_params)

        def test__given_missing_progress__computes_progress_from_completed_years(
            self, economy_service
        ):
            result = economy_service._build_budget_window_computing_result(
                total_years=4,
                years=BudgetWindowYearProgress(
                    completed_years=["2026"],
                    computing_years=["2027", "2028", "2029"],
                    queued_years=[],
                ),
                progress=None,
            )

            assert result.progress == 25
            assert result.message == "Scoring 2027, 2028 + 1 more (1 of 4 complete)..."

        def test__given_no_active_or_queued_years__uses_generic_progress_message(
            self, economy_service
        ):
            result = economy_service._build_budget_window_computing_result(
                total_years=3,
                years=BudgetWindowYearProgress(
                    completed_years=["2026"],
                    computing_years=[],
                    queued_years=[],
                ),
                progress=None,
            )

            assert result.progress == 33
            assert result.message == "Scoring budget window (1 of 3 complete)..."
