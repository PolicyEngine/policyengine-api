"""Budget-window requests: claim a report's batch submission and submit it once."""

from dataclasses import replace
from typing import Any

import httpx

from policyengine_api.gcp_logging import logger
from policyengine_api.libs.simulation_entrypoint import ModalBudgetWindowBatchExecution
from policyengine_api.observability import runtime as observability_runtime
from policyengine_api.observability import set_runtime_context
from policyengine_api.observability.stages import ECONOMY_BUDGET_WINDOW_STAGES, Stage
from policyengine_api.request_context import (
    incoming_observability_id,
    resolve_observability_id,
    restore_observability_id,
    start_observability_id,
)
from policyengine_api.runtime_cache.core import CacheCoordinationError
from policyengine_api.services.economic_impact_request import EconomicImpactRequest
from policyengine_api.services.economy_impact_types import (
    BUDGET_WINDOW_CLAIM_ATTEMPTS,
    BUDGET_WINDOW_MAX_ACTIVE_YEARS,
    BUDGET_WINDOW_SUBMISSION_VALIDATION_ERROR_STATUS_CODES,
    BudgetWindowEconomicImpactResult,
    BudgetWindowYearProgress,
    EconomicImpactSetupOptions,
    ImpactPolicies,
    SimulationOptions,
)
from policyengine_api.utils import budget_window as budget_window_utils


class BudgetWindowSubmissionMixin:
    """Answer a budget-window request, submitting its batch job only once."""

    @observability_runtime.span(
        ECONOMY_BUDGET_WINDOW_STAGES.name(Stage.ECONOMY_BUDGET_WINDOW_REQUEST)
    )
    def get_budget_window_economic_impact(
        self,
        impact_request: EconomicImpactRequest,
        *,
        start_year: str,
        window_size: int,
        max_active_years: int = BUDGET_WINDOW_MAX_ACTIVE_YEARS,
    ) -> BudgetWindowEconomicImpactResult:
        """Return the multi-year budget-window impact, submitting a batch job if needed.

        The shared cache records each report's state (starting, submitted, completed or
        failed) so concurrent requests share one batch job; later calls poll it and
        report progress until it finishes. Raise CacheCoordinationError if the cache is
        unavailable or submission ownership keeps changing, and SPMValidationError when
        the SPM selection or a stored result cannot be certified.
        """
        set_runtime_context(
            country_id=impact_request.country_id,
            policy_id=impact_request.policy_id,
            baseline_policy_id=impact_request.baseline_policy_id,
            start_year=start_year,
            window_size=window_size,
        )
        try:
            impact_request = self._with_normalized_region(impact_request)

            budget_window_setup = budget_window_utils.build_budget_window_request_setup(
                start_year=start_year,
                window_size=window_size,
                target=impact_request.target,
            )
            setup_options = self._build_economic_impact_setup_options(
                replace(impact_request, options=dict(impact_request.options)),
                time_period=budget_window_setup.time_period,
            )
            cache_key = self._build_budget_window_cache_key(setup_options)

            cached_state = self._budget_window_cache.get_state(cache_key)
            if cached_state is not None:
                self._restore_budget_window_observability_id(
                    cached_state.observability_id,
                    setup_options=setup_options,
                )
                cached_result = self._budget_window_result_from_state(
                    cached_state,
                    setup_options=setup_options,
                    cache_key=cache_key,
                    years=budget_window_setup.years,
                )
                if cached_result is not None:
                    return cached_result

            return self._submit_budget_window(
                setup_options,
                cache_key,
                budget_window_setup,
                max_active_years=max_active_years,
            )
        except Exception as e:
            logger.log_struct(
                {
                    "message": "Error getting budget-window economic impact",
                    "error_type": type(e).__name__,
                },
                severity="ERROR",
            )
            raise

    def _submit_budget_window(
        self,
        setup_options: EconomicImpactSetupOptions,
        cache_key: str,
        budget_window_setup: budget_window_utils.BudgetWindowRequestSetup,
        *,
        max_active_years: int,
    ) -> BudgetWindowEconomicImpactResult:
        """Submit the batch job if this request wins the claim, and report it queued.

        Both policies load first, so a request naming a policy its country does
        not have raises PolicyNotFoundError before it claims the submission. A
        request that loses the claim reports the window queued without
        submitting; a submission the gateway rejects as invalid is a failed result.
        """
        policies = self._get_policy_jsons(
            setup_options.country_id,
            setup_options.baseline_policy_id,
            setup_options.reform_policy_id,
        )
        years = budget_window_setup.years
        cache_status = "starting-claim-hit"
        observability_id_candidate = resolve_observability_id(
            incoming_observability_id()
        )
        owns_claim = self._claim_budget_window_start(
            cache_key,
            setup_options.submission_claim_id,
            observability_id_candidate,
            setup_options=setup_options,
        )

        if owns_claim:
            cache_status = "miss"
            rejected_result = self._submit_claimed_budget_window_batch(
                setup_options,
                cache_key,
                budget_window_setup,
                max_active_years=max_active_years,
                policies=policies,
            )
            if rejected_result is not None:
                return rejected_result
        return self._build_budget_window_computing_result(
            total_years=len(years),
            years=BudgetWindowYearProgress(
                completed_years=[],
                computing_years=[],
                queued_years=years,
            ),
            progress=0,
            cache_status=cache_status,
        )

    def _submit_claimed_budget_window_batch(
        self,
        setup_options: EconomicImpactSetupOptions,
        cache_key: str,
        budget_window_setup: budget_window_utils.BudgetWindowRequestSetup,
        *,
        max_active_years: int,
        policies: ImpactPolicies,
    ) -> BudgetWindowEconomicImpactResult | None:
        """Submit the batch this request claimed and record its job ID.

        Return a failed result when the gateway rejects the submission as invalid,
        otherwise None. On any other error release the claim and re-raise.
        """
        claim_token = setup_options.submission_claim_id
        try:
            batch_execution = self._start_budget_window_batch(
                setup_options=setup_options,
                start_year=budget_window_setup.start_year,
                window_size=budget_window_setup.window_size,
                max_parallel=max_active_years,
                policies=policies,
            )
            self._budget_window_cache.store_submitted(
                cache_key,
                batch_execution.batch_job_id,
                setup_options.observability_id,
            )
        except httpx.HTTPStatusError as error:
            if (
                error.response.status_code
                in BUDGET_WINDOW_SUBMISSION_VALIDATION_ERROR_STATUS_CODES
            ):
                failed_result = BudgetWindowEconomicImpactResult.failed(
                    self._build_submission_error_message(error),
                    queued_years=budget_window_setup.years,
                    cache_status="miss",
                )
                self._budget_window_cache.set_execution_failure(
                    cache_key,
                    failed_result.model_dump(mode="json"),
                    setup_options.observability_id,
                )
                return failed_result
            self._budget_window_cache.clear_starting_claim(
                cache_key,
                claim_token,
                setup_options.observability_id,
            )
            raise
        except Exception:
            self._budget_window_cache.clear_starting_claim(
                cache_key,
                claim_token,
                setup_options.observability_id,
            )
            raise
        return None

    def _claim_budget_window_start(
        self,
        cache_key: str,
        claim_token: str,
        observability_id_candidate: str,
        *,
        setup_options: EconomicImpactSetupOptions,
    ) -> bool:
        """Claim this report's batch submission, or adopt another request's state.

        Return True when this request now owns the submission and False once another
        request's stored state is found. Raise CacheCoordinationError if ownership
        keeps changing.
        """
        for _attempt in range(BUDGET_WINDOW_CLAIM_ATTEMPTS):
            if self._budget_window_cache.claim_batch_start(
                cache_key,
                claim_token,
                observability_id_candidate,
            ):
                setup_options.observability_id = start_observability_id(
                    observability_id_candidate
                )
                return True
            claimed_state = self._budget_window_cache.get_state(cache_key)
            if claimed_state is not None:
                self._restore_budget_window_observability_id(
                    claimed_state.observability_id,
                    setup_options=setup_options,
                )
                return False
        msg = "budget-window submission ownership changed repeatedly"
        raise CacheCoordinationError(msg)

    def _build_budget_window_cache_key(
        self,
        setup_options: EconomicImpactSetupOptions,
    ) -> str:
        return self._budget_window_cache.build_key(
            scope=self._reform_impact_scope(setup_options),
            options_hash=setup_options.options_hash,
            api_version=setup_options.api_version,
        )

    @staticmethod
    def _restore_budget_window_observability_id(
        value: str | None,
        *,
        setup_options: EconomicImpactSetupOptions,
    ) -> str | None:
        resolved = restore_observability_id(value)
        if resolved is None:
            return setup_options.observability_id
        setup_options.observability_id = resolved
        return resolved

    def _build_budget_window_batch_payload(
        self,
        *,
        setup_options: EconomicImpactSetupOptions,
        start_year: str,
        window_size: int,
        max_parallel: int,
        policies: ImpactPolicies,
    ) -> dict[str, Any]:
        sim_config: SimulationOptions = self._setup_sim_options(
            setup_options,
            reform_policy=policies.reform,
            baseline_policy=policies.baseline,
            time_period=start_year,
            include_cliffs=False,
        )
        sim_params = sim_config.model_dump()
        sim_params.pop("time_period", None)
        sim_params["start_year"] = start_year
        sim_params["window_size"] = window_size
        sim_params["max_parallel"] = max_parallel
        sim_params["target"] = setup_options.target
        return sim_params

    @observability_runtime.span(
        ECONOMY_BUDGET_WINDOW_STAGES.name(Stage.ECONOMY_START_BUDGET_WINDOW)
    )
    def _start_budget_window_batch(
        self,
        *,
        setup_options: EconomicImpactSetupOptions,
        start_year: str,
        window_size: int,
        max_parallel: int,
        policies: ImpactPolicies,
    ) -> ModalBudgetWindowBatchExecution:
        sim_params = self._build_budget_window_batch_payload(
            setup_options=setup_options,
            start_year=start_year,
            window_size=window_size,
            max_parallel=max_parallel,
            policies=policies,
        )

        logger.log_struct(
            {
                "message": "Submitting budget-window batch job",
                **setup_options.model_dump(),
                "start_year": start_year,
                "window_size": window_size,
                "max_parallel": max_parallel,
            },
            severity="INFO",
        )

        return self._simulation_gateway.run_budget_window_batch(sim_params)
