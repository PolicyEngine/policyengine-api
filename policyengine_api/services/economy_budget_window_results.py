"""Budget-window results: replay a report's stored state, or poll its batch job."""

from policyengine_api.constants import (
    EXECUTION_STATUSES_FAILURE,
    EXECUTION_STATUSES_PENDING,
    EXECUTION_STATUSES_SUCCESS,
)
from policyengine_api.observability import runtime as observability_runtime
from policyengine_api.observability.stages import ECONOMY_BUDGET_WINDOW_STAGES, Stage
from policyengine_api.services.budget_window_cache import BudgetWindowCacheState
from policyengine_api.services.economy_impact_types import (
    BUDGET_WINDOW_LISTED_COMPUTING_YEARS,
    BudgetWindowEconomicImpactResult,
    BudgetWindowYearProgress,
    EconomicImpactSetupOptions,
)
from policyengine_api.spm import SPMValidationError
from policyengine_api.worker_spm import validate_worker_result


class BudgetWindowResultsMixin:
    """Turn a budget-window report's stored state or batch job into its result."""

    def _budget_window_result_from_state(
        self,
        cached_state: BudgetWindowCacheState,
        *,
        setup_options: EconomicImpactSetupOptions,
        cache_key: str,
        years: list[str],
    ) -> BudgetWindowEconomicImpactResult | None:
        """Answer from this report's stored state, or None if it gives no answer.

        A failure is replayed, a completed result is certified and returned, a
        submitted batch is polled, and a starting claim reports every year queued.
        """
        if cached_state.status == "failed":
            return self._replay_budget_window_failure(cached_state)

        if cached_state.status == "completed":
            return self._replay_budget_window_result(
                cached_state,
                setup_options=setup_options,
                cache_key=cache_key,
                years=years,
            )

        if cached_state.status == "submitted":
            return self._poll_submitted_budget_window(
                cached_state,
                setup_options=setup_options,
                cache_key=cache_key,
                years=years,
            )

        if cached_state.status == "starting":
            return self._build_budget_window_computing_result(
                total_years=len(years),
                years=BudgetWindowYearProgress(
                    completed_years=[],
                    computing_years=[],
                    queued_years=years,
                ),
                progress=0,
                cache_status="starting-claim-hit",
            )
        return None

    def _replay_budget_window_result(
        self,
        cached_state: BudgetWindowCacheState,
        *,
        setup_options: EconomicImpactSetupOptions,
        cache_key: str,
        years: list[str],
    ) -> BudgetWindowEconomicImpactResult:
        """Return a stored budget-window result after certifying its SPM receipts."""
        cached_result = cached_state.result or {}
        try:
            validate_worker_result(
                cached_result,
                setup_options.options.get("spm"),
                expected_years=years,
            )
        except SPMValidationError as error:
            # A stored payload this build cannot certify is terminal, not
            # transient: the selection is part of this cache key, so a
            # recomputation would submit the identical job and store the
            # identical receipts. Record it the way the batch poll does
            # and the read above replays it, instead of re-deriving the
            # same failure from the same payload on every later poll.
            self._budget_window_cache.set_terminal_error(
                cache_key,
                error.to_dict(),
                setup_options.observability_id,
            )
            raise
        return BudgetWindowEconomicImpactResult.completed(
            cached_result,
            cache_status="result-hit",
        )

    def _poll_submitted_budget_window(
        self,
        cached_state: BudgetWindowCacheState,
        *,
        setup_options: EconomicImpactSetupOptions,
        cache_key: str,
        years: list[str],
    ) -> BudgetWindowEconomicImpactResult:
        """Poll the batch job this report's stored state says was submitted."""
        return self._get_budget_window_result_from_batch_job_id(
            batch_job_id=cached_state.batch_job_id or "",
            cache_key=cache_key,
            setup_options=setup_options,
            queued_years_on_submit=years,
            cache_status="batch-id-hit",
        )

    @staticmethod
    def _replay_budget_window_failure(
        cached_state: BudgetWindowCacheState,
    ) -> BudgetWindowEconomicImpactResult:
        """Replay a stored failure: raise its typed SPM error or return its result."""
        if cached_state.failure_type == "spm_validation":
            cached_error = cached_state.error or {}
            raise SPMValidationError(
                code=str(cached_error.get("code", "SPM_VALIDATION_ERROR")),
                message=str(
                    cached_error.get(
                        "message", "Stored budget-window validation failed"
                    )
                ),
            )
        return BudgetWindowEconomicImpactResult.model_validate(
            cached_state.error
        ).model_copy(update={"cache_status": "failure-hit"})

    @observability_runtime.span(
        ECONOMY_BUDGET_WINDOW_STAGES.name(Stage.ECONOMY_POLL_BUDGET_WINDOW)
    )
    def _get_budget_window_result_from_batch_job_id(
        self,
        *,
        batch_job_id: str,
        cache_key: str,
        setup_options: EconomicImpactSetupOptions,
        queued_years_on_submit: list[str],
        cache_status: str | None = None,
    ) -> BudgetWindowEconomicImpactResult:
        total_years = len(queued_years_on_submit)
        spm = setup_options.options.get("spm")
        resolved_observability_id = setup_options.observability_id
        try:
            batch_execution = self._simulation_gateway.get_budget_window_batch_by_id(
                batch_job_id
            )
            if batch_execution.status in EXECUTION_STATUSES_SUCCESS:
                result = batch_execution.result
                if isinstance(result, dict) and result:
                    validate_worker_result(
                        result, spm, expected_years=queued_years_on_submit
                    )
        except SPMValidationError as error:
            self._budget_window_cache.set_terminal_error(
                cache_key,
                error.to_dict(),
                resolved_observability_id,
            )
            raise

        if batch_execution.status in EXECUTION_STATUSES_SUCCESS:
            result = batch_execution.result
            if not isinstance(result, dict) or not result:
                failed_result = BudgetWindowEconomicImpactResult.failed(
                    "Budget-window batch completed without a result",
                    completed_years=batch_execution.completed_years,
                    computing_years=batch_execution.running_years,
                    queued_years=batch_execution.queued_years or queued_years_on_submit,
                    cache_status=cache_status,
                )
                self._budget_window_cache.set_execution_failure(
                    cache_key,
                    failed_result.model_dump(mode="json"),
                    resolved_observability_id,
                )
                return failed_result
            self._budget_window_cache.set_completed_result(
                cache_key,
                result,
                resolved_observability_id,
            )
            return BudgetWindowEconomicImpactResult.completed(
                result,
                cache_status=cache_status,
            )

        if batch_execution.status in EXECUTION_STATUSES_FAILURE:
            error_message = batch_execution.error or "Budget-window batch failed"
            failed_result = BudgetWindowEconomicImpactResult.failed(
                error_message,
                completed_years=batch_execution.completed_years,
                computing_years=batch_execution.running_years,
                queued_years=batch_execution.queued_years or queued_years_on_submit,
                cache_status=cache_status,
            )
            self._budget_window_cache.set_execution_failure(
                cache_key,
                failed_result.model_dump(mode="json"),
                resolved_observability_id,
            )
            return failed_result

        if batch_execution.status in EXECUTION_STATUSES_PENDING:
            return self._build_budget_window_computing_result(
                total_years=total_years,
                years=BudgetWindowYearProgress(
                    completed_years=batch_execution.completed_years,
                    computing_years=batch_execution.running_years,
                    queued_years=batch_execution.queued_years,
                ),
                progress=batch_execution.progress,
                cache_status=cache_status,
            )

        msg = (
            f"Unexpected budget-window batch execution state: {batch_execution.status}"
        )
        raise ValueError(msg)

    def _build_budget_window_computing_result(
        self,
        *,
        total_years: int,
        years: BudgetWindowYearProgress,
        progress: int | None = None,
        cache_status: str | None = None,
    ) -> BudgetWindowEconomicImpactResult:
        resolved_progress = progress
        if resolved_progress is None:
            resolved_progress = round((len(years.completed_years) / total_years) * 100)

        return BudgetWindowEconomicImpactResult.computing(
            progress=resolved_progress,
            years=years,
            message=self._build_budget_window_progress_message(
                completed_years=years.completed_years,
                total_years=total_years,
                computing_years=years.computing_years,
                queued_years=years.queued_years,
            ),
            cache_status=cache_status,
        )

    def _build_budget_window_progress_message(
        self,
        *,
        completed_years: list[str],
        total_years: int,
        computing_years: list[str],
        queued_years: list[str],
    ) -> str:
        completed_count = len(completed_years)
        if computing_years:
            active_years = ", ".join(
                computing_years[:BUDGET_WINDOW_LISTED_COMPUTING_YEARS]
            )
            if len(computing_years) > BUDGET_WINDOW_LISTED_COMPUTING_YEARS:
                unlisted_count = (
                    len(computing_years) - BUDGET_WINDOW_LISTED_COMPUTING_YEARS
                )
                active_years = f"{active_years} + {unlisted_count} more"
            return (
                f"Scoring {active_years} "
                f"({completed_count} of {total_years} complete)..."
            )

        if queued_years:
            return (
                f"Queued {queued_years[0]} "
                f"({completed_count} of {total_years} complete)..."
            )

        return f"Scoring budget window ({completed_count} of {total_years} complete)..."
