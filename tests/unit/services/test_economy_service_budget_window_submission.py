"""Budget-window impacts: claiming and submitting the batch job, and its refusals."""

from unittest.mock import call, patch

import httpx
import pytest

from policyengine_api.runtime_cache.core import CacheCoordinationError
from policyengine_api.services.budget_window_cache import BudgetWindowCacheState
from policyengine_api.services.economy_service import ImpactStatus
from tests.fixtures.services.economy_service import (
    MOCK_OBSERVABILITY_ID,
    MOCK_SUBMISSION_CLAIM_ID,
    create_mock_budget_window_batch_execution,
)
from tests.fixtures.services.economy_service_helpers import (
    GetBudgetWindowEconomicImpactFixtures,
    make_http_status_error,
)

pytest_plugins = ("tests.fixtures.services.economy_service",)
pytestmark = pytest.mark.usefixtures("stable_observability_lifecycle")


class TestEconomyService:
    class TestGetBudgetWindowEconomicImpact(GetBudgetWindowEconomicImpactFixtures):
        def test__given_no_cached_batch__submits_parent_batch_and_returns_queued_result(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            batch_execution = create_mock_budget_window_batch_execution(
                batch_job_id="fc-budget-123",
                status="submitted",
            )
            mock_simulation_entrypoint.run_budget_window_batch.return_value = (
                batch_execution
            )

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            assert result.progress == 0
            assert result.completed_years == []
            assert result.computing_years == []
            assert result.queued_years == ["2026", "2027", "2028"]
            assert result.cache_status == "miss"
            assert "Queued 2026" in result.message
            mock_simulation_entrypoint.run_budget_window_batch.assert_called_once()
            submitted_payload = (
                mock_simulation_entrypoint.run_budget_window_batch.call_args.args[0]
            )
            assert submitted_payload["start_year"] == "2026"
            assert submitted_payload["window_size"] == 3
            assert submitted_payload["max_parallel"] == 20
            assert submitted_payload["target"] == "general"
            assert "time_period" not in submitted_payload
            mock_budget_window_cache.claim_batch_start.assert_called_once_with(
                "budget-window-cache-key",
                MOCK_SUBMISSION_CLAIM_ID,
                MOCK_OBSERVABILITY_ID,
            )
            mock_budget_window_cache.store_submitted.assert_called_once_with(
                "budget-window-cache-key",
                "fc-budget-123",
                MOCK_OBSERVABILITY_ID,
            )
            mock_reform_impacts_service.set_reform_impact.assert_not_called()

        def test__given_existing_start_claim__does_not_submit_duplicate_batch(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            winning_observability_id = "00000000-0000-4000-8000-000000000099"
            mock_budget_window_cache.claim_batch_start.return_value = False
            mock_budget_window_cache.get_state.side_effect = [
                None,
                BudgetWindowCacheState(
                    status="starting",
                    submission_claim_id="winning-claim",
                    observability_id=winning_observability_id,
                ),
            ]

            with (
                patch(
                    "policyengine_api.services.economy_budget_window_submission.restore_observability_id",
                    return_value=winning_observability_id,
                ) as restore_observability_id,
                patch(
                    "policyengine_api.services.economy_budget_window_submission.start_observability_id"
                ) as start_observability_id,
            ):
                result = economy_service.get_budget_window_economic_impact(
                    **base_params
                )

            assert result.status == ImpactStatus.COMPUTING
            assert result.progress == 0
            assert result.queued_years == ["2026", "2027", "2028"]
            assert result.cache_status == "starting-claim-hit"
            restore_observability_id.assert_called_with(winning_observability_id)
            start_observability_id.assert_not_called()
            mock_simulation_entrypoint.run_budget_window_batch.assert_not_called()

        def test__given_disappearing_start_claim__retries_before_binding_identity(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            lifecycle_events = []
            claim_results = iter([False, True])
            mock_budget_window_cache.claim_batch_start.side_effect = lambda *_args: (
                lifecycle_events.append("claim") or next(claim_results)
            )
            mock_budget_window_cache.get_state.side_effect = [None, None]
            mock_simulation_entrypoint.run_budget_window_batch.return_value = (
                create_mock_budget_window_batch_execution(
                    batch_job_id="fc-budget-123",
                    status="submitted",
                )
            )

            with patch(
                "policyengine_api.services.economy_budget_window_submission.start_observability_id",
                side_effect=lambda value: lifecycle_events.append("bind") or value,
            ) as start_observability_id:
                result = economy_service.get_budget_window_economic_impact(
                    **base_params
                )

            assert result.status == ImpactStatus.COMPUTING
            assert result.cache_status == "miss"
            assert mock_budget_window_cache.claim_batch_start.call_count == 2
            assert mock_budget_window_cache.claim_batch_start.call_args_list == [
                call(
                    "budget-window-cache-key",
                    MOCK_SUBMISSION_CLAIM_ID,
                    MOCK_OBSERVABILITY_ID,
                ),
                call(
                    "budget-window-cache-key",
                    MOCK_SUBMISSION_CLAIM_ID,
                    MOCK_OBSERVABILITY_ID,
                ),
            ]
            start_observability_id.assert_called_once_with(MOCK_OBSERVABILITY_ID)
            assert lifecycle_events == ["claim", "claim", "bind"]
            mock_simulation_entrypoint.run_budget_window_batch.assert_called_once()

        def test__given_repeated_disappearing_claims__fails_without_binding_identity(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            mock_budget_window_cache.claim_batch_start.return_value = False
            mock_budget_window_cache.get_state.return_value = None

            with (
                patch(
                    "policyengine_api.services.economy_budget_window_submission.start_observability_id"
                ) as start_observability_id,
                pytest.raises(
                    CacheCoordinationError,
                    match="submission ownership changed repeatedly",
                ),
            ):
                economy_service.get_budget_window_economic_impact(**base_params)

            assert mock_budget_window_cache.claim_batch_start.call_count == 3
            start_observability_id.assert_not_called()
            mock_simulation_entrypoint.run_budget_window_batch.assert_not_called()

        def test__given_gateway_raises_before_returning_batch__clears_start_claim(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            mock_simulation_entrypoint.run_budget_window_batch.side_effect = (
                RuntimeError("submit failed")
            )

            with pytest.raises(RuntimeError, match="submit failed"):
                economy_service.get_budget_window_economic_impact(**base_params)

            mock_budget_window_cache.clear_starting_claim.assert_called_once_with(
                "budget-window-cache-key",
                MOCK_SUBMISSION_CLAIM_ID,
                MOCK_OBSERVABILITY_ID,
            )

        @pytest.mark.parametrize("status_code", [400, 422])
        def test__given_modal_rejects_invalid_batch_submission__returns_failed_result(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
            status_code,
        ):
            rejection = make_http_status_error(
                status_code,
                {
                    "detail": (
                        "Invalid Hugging Face dataset URI: "
                        "'hf://policyengine/nonexistent-budget-window-test.h5@0.0.0'"
                    )
                },
            )
            mock_simulation_entrypoint.run_budget_window_batch.side_effect = rejection

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.ERROR
            assert result.data is None
            assert result.error == (
                "Invalid Hugging Face dataset URI: "
                "'hf://policyengine/nonexistent-budget-window-test.h5@0.0.0'"
            )
            assert result.completed_years == []
            assert result.computing_years == []
            assert result.queued_years == ["2026", "2027", "2028"]
            assert result.cache_status == "miss"
            mock_budget_window_cache.clear_starting_claim.assert_not_called()
            mock_budget_window_cache.set_execution_failure.assert_called_once()

        @pytest.mark.parametrize("status_code", [401, 403, 429, 500])
        def test__given_modal_non_validation_error_on_batch_submission__raises(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
            status_code,
        ):
            mock_simulation_entrypoint.run_budget_window_batch.side_effect = (
                make_http_status_error(status_code, {"detail": "gateway unavailable"})
            )

            with pytest.raises(httpx.HTTPStatusError):
                economy_service.get_budget_window_economic_impact(**base_params)

            mock_budget_window_cache.clear_starting_claim.assert_called_once_with(
                "budget-window-cache-key",
                MOCK_SUBMISSION_CLAIM_ID,
                MOCK_OBSERVABILITY_ID,
            )
            mock_budget_window_cache.store_submitted.assert_not_called()

        @pytest.mark.parametrize(
            ("payload", "expected_message"),
            [
                ({"message": "gateway validation failed"}, "gateway validation failed"),
                ({"error": "invalid request"}, "invalid request"),
            ],
        )
        def test__given_modal_validation_json_error__extracts_message(
            self, economy_service, payload, expected_message
        ):
            error = make_http_status_error(400, payload)

            message = economy_service._build_submission_error_message(error)

            assert message == expected_message

        def test__given_modal_validation_error_list__names_each_field(
            self, economy_service
        ):
            error = make_http_status_error(
                422,
                {
                    "detail": [
                        {
                            "type": "missing",
                            "loc": ["body", "start_year"],
                            "msg": "Field required",
                            "input": {},
                        },
                        {
                            "type": "extra_forbidden",
                            "loc": ["body", "breakdown"],
                            "msg": "Extra inputs are not permitted",
                            "input": "local_areas",
                        },
                    ]
                },
            )

            message = economy_service._build_submission_error_message(error)

            assert message == (
                "body.start_year: Field required; "
                "body.breakdown: Extra inputs are not permitted"
            )

        def test__given_modal_rejects_batch_with_error_list__names_each_field(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            mock_simulation_entrypoint.run_budget_window_batch.side_effect = (
                make_http_status_error(
                    422,
                    {
                        "detail": [
                            {
                                "type": "less_than_equal",
                                "loc": ["body", "window_size"],
                                "msg": "Input should be less than or equal to 75",
                                "input": 80,
                            }
                        ]
                    },
                )
            )

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.ERROR
            assert result.error == (
                "body.window_size: Input should be less than or equal to 75"
            )
            mock_budget_window_cache.set_execution_failure.assert_called_once()

        def test__given_modal_validation_plain_text_error__extracts_response_text(
            self, economy_service
        ):
            error = make_http_status_error(400, text="plain validation failed")

            message = economy_service._build_submission_error_message(error)

            assert message == "plain validation failed"

        def test__given_modal_validation_empty_error__falls_back_to_exception_text(
            self, economy_service
        ):
            error = make_http_status_error(400, text="")

            message = economy_service._build_submission_error_message(error)

            assert message == str(error)
