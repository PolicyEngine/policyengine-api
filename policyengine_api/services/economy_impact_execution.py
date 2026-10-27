"""Single-year simulations: submit one, follow its execution, read its result."""

import contextlib

import httpx

from policyengine_api.constants import (
    EXECUTION_STATUSES_FAILURE,
    EXECUTION_STATUSES_PENDING,
    EXECUTION_STATUSES_SUCCESS,
)
from policyengine_api.data.v1_models import ReformImpact
from policyengine_api.gcp_logging import logger
from policyengine_api.libs.simulation_entrypoint import ModalSimulationExecution
from policyengine_api.observability import runtime as observability_runtime
from policyengine_api.observability.stages import ECONOMY_ANNUAL_STAGES, Stage
from policyengine_api.runtime_cache.reform_impacts import CachedReformImpact
from policyengine_api.services.economic_impact_request import LOCAL_AREA_BREAKDOWN
from policyengine_api.services.economy_impact_types import (
    LOCAL_AREA_BREAKDOWN_FAILURE_SECONDS,
    LOCAL_AREA_BREAKDOWN_RETRY_NOTE,
    EconomicImpactResult,
    EconomicImpactSetupOptions,
    SimulationOptions,
)
from policyengine_api.services.reform_impacts_service import ReformImpactHandoffError
from policyengine_api.spm import SPMValidationError
from policyengine_api.worker_spm import validate_worker_result


class ImpactExecutionMixin:
    """Submit a single-year simulation; answer from its execution or stored result."""

    @observability_runtime.span(
        ECONOMY_ANNUAL_STAGES.name(Stage.ECONOMY_HANDLE_EXECUTION_STATE)
    )
    def _handle_execution_state(
        self,
        setup_options: EconomicImpactSetupOptions,
        execution_state: str,
        reform_impact: CachedReformImpact,
        execution: ModalSimulationExecution | None = None,
    ) -> EconomicImpactResult:
        """Map an execution's state to the impact status and result to return.

        Supports both GCP Workflow statuses (SUCCEEDED, FAILED, ACTIVE) and
        Modal statuses (complete, failed, running, submitted).
        """
        if execution_state in EXECUTION_STATUSES_SUCCESS:
            raw_result = self._simulation_gateway.get_execution_result(execution)
            kind_error = self._breakdown_result_kind_error(setup_options, raw_result)
            if kind_error is not None:
                return self._record_breakdown_failure(
                    setup_options, reform_impact, kind_error
                )
            result = self._with_policyengine_bundle(
                result=raw_result,
                setup_options=setup_options,
                execution=execution,
            )
            validate_worker_result(
                result,
                setup_options.options.get("spm"),
                expected_year=setup_options.time_period,
            )
            self._set_reform_impact_complete(
                setup_options=setup_options,
                reform_impact_json=result,
                execution_id=reform_impact.execution_id,
            )
            logger.log_struct(
                {"message": "Sim API execution completed"},
                severity="INFO",
            )
            return EconomicImpactResult.completed(data=result)

        if execution_state in EXECUTION_STATUSES_FAILURE:
            # For Modal, try to get error message from execution
            error_message = "Simulation entrypoint execution failed"
            if (
                execution is not None
                and hasattr(execution, "error")
                and execution.error
            ):
                error_message = (
                    f"Simulation entrypoint execution failed: {execution.error}"
                )
            if setup_options.options.get("breakdown") is not None:
                return self._record_breakdown_failure(
                    setup_options, reform_impact, error_message
                )

            self._set_reform_impact_error(
                setup_options=setup_options,
                message=error_message,
                execution_id=reform_impact.execution_id,
            )
            logger.log_struct(
                {"message": error_message},
                severity="ERROR",
            )
            return EconomicImpactResult.error(message=error_message)

        if execution_state in EXECUTION_STATUSES_PENDING:
            logger.log_struct(
                {"message": "Sim API execution is still running"},
                severity="INFO",
            )
            return EconomicImpactResult.computing(
                run_progress=execution.run_progress if execution is not None else None
            )

        msg = f"Unexpected sim API execution state: {execution_state}"
        raise ValueError(msg)

    @staticmethod
    def _breakdown_result_kind_error(
        setup_options: EconomicImpactSetupOptions, result: object
    ) -> str | None:
        """Return why a breakdown job's result cannot be stored, if it cannot.

        A breakdown request needs the simulation API's local-area result
        (``kind: local_areas``). Any other result, such as a national one from
        a release that ignored the field, must never be stored under the
        breakdown's options hash. Return None for a valid result and for every
        request without a breakdown.
        """
        if setup_options.options.get("breakdown") is None:
            return None
        kind = result.get("kind") if isinstance(result, dict) else None
        if kind == LOCAL_AREA_BREAKDOWN:
            return None
        return (
            f"The simulation API returned a result of kind {kind!r} for a "
            "local-area breakdown request, which needs kind "
            f"{LOCAL_AREA_BREAKDOWN!r}; the result was not stored"
        )

    def _record_breakdown_failure(
        self,
        setup_options: EconomicImpactSetupOptions,
        reform_impact: CachedReformImpact,
        reason: str,
    ) -> EconomicImpactResult:
        """Keep a failed breakdown job's error for two minutes, then let it go.

        A breakdown runs on the large local-area dataset, where a timeout or
        memory failure may not repeat, so its failure is not kept for the usual
        30 days. This job's own record, found by its execution ID, becomes an
        error that expires after ``LOCAL_AREA_BREAKDOWN_FAILURE_SECONDS``.
        Until then every request gets the same error, which says when to try
        again; after it, the next request finds no record and submits a new
        job. No other job's record is read or changed, and no submission claim
        is held at this point: it was released once the job was handed off.
        Failures of requests without a breakdown are stored as before.
        """
        message = f"{reason}. {LOCAL_AREA_BREAKDOWN_RETRY_NOTE}"
        if reform_impact.execution_id:
            self._set_reform_impact_error(
                setup_options=setup_options,
                message=message,
                execution_id=reform_impact.execution_id,
                keep_seconds=LOCAL_AREA_BREAKDOWN_FAILURE_SECONDS,
            )
        return EconomicImpactResult.error(message=message)

    @observability_runtime.span(
        ECONOMY_ANNUAL_STAGES.name(Stage.ECONOMY_READ_COMPLETED)
    )
    def _handle_completed_impact(
        self,
        setup_options: EconomicImpactSetupOptions,
        most_recent_impact: ReformImpact,
    ) -> EconomicImpactResult:
        result = self._parse_json_object(most_recent_impact.reform_impact_json)
        try:
            validate_worker_result(
                result,
                setup_options.options.get("spm"),
                expected_year=setup_options.time_period,
            )
        except SPMValidationError as error:
            self._record_uncertifiable_stored_impact(
                setup_options=setup_options,
                most_recent_impact=most_recent_impact,
                error=error,
            )
            raise
        return EconomicImpactResult.completed(
            data=self._with_policyengine_bundle(
                result=result,
                setup_options=setup_options,
            )
        )

    def _record_uncertifiable_stored_impact(
        self,
        setup_options: EconomicImpactSetupOptions,
        most_recent_impact: ReformImpact,
        error: SPMValidationError,
    ) -> None:
        """Persist a stored result's certification failure, best effort.

        Later polls then replay the typed failure from storage rather than
        re-deriving it from a payload this build cannot certify, which otherwise
        leaves the caller with no terminal state to reach.

        Only this request's own record is marked. `_get_most_recent_impact` can
        fall back to a record matched by options-hash prefix, and marking that
        one terminal would wedge the caller whose spelling owns it.

        The caller's answer is the typed error either way, so a storage failure
        here — already logged by `_set_reform_impact_error` — must not replace it.
        """
        if not most_recent_impact.execution_id:
            return
        if most_recent_impact.options_hash != setup_options.options_hash:
            return
        # Best effort: the typed SPM error is the answer, and the failure is
        # already logged.
        with contextlib.suppress(Exception):
            self._set_reform_impact_error(
                setup_options=setup_options,
                message=error.message,
                error_code=error.code,
                execution_id=most_recent_impact.execution_id,
            )

    @observability_runtime.span(ECONOMY_ANNUAL_STAGES.name(Stage.ECONOMY_READ_FAILED))
    def _handle_failed_impact(
        self,
        most_recent_impact: ReformImpact,
    ) -> EconomicImpactResult:
        if getattr(most_recent_impact, "error_code", None):
            # A typed SPM failure is terminal. Replay its code on every later
            # poll rather than flattening it into an untyped upstream failure:
            # the caller needs the code to know the deployment, not the job,
            # is what cannot serve the request.
            raise SPMValidationError(
                most_recent_impact.error_code, most_recent_impact.message
            )
        # Failed executions have no successful output or SPM receipts to
        # validate. Replay their original failure on every later poll.
        return EconomicImpactResult.error(
            message=(
                most_recent_impact.message or "Simulation entrypoint execution failed"
            )
        )

    @observability_runtime.span(ECONOMY_ANNUAL_STAGES.name(Stage.ECONOMY_POLL_ACTIVE))
    def _handle_computing_impact(
        self,
        setup_options: EconomicImpactSetupOptions,
        most_recent_impact: ReformImpact,
    ) -> EconomicImpactResult:
        try:
            execution = self._simulation_gateway.get_execution_by_id(
                most_recent_impact.execution_id
            )
            execution_state = self._simulation_gateway.get_execution_status(execution)
            return self._handle_execution_state(
                execution_state=execution_state,
                setup_options=setup_options,
                reform_impact=most_recent_impact,
                execution=execution,
            )
        except SPMValidationError as error:
            self._set_reform_impact_error(
                setup_options=setup_options,
                message=error.message,
                error_code=error.code,
                execution_id=most_recent_impact.execution_id,
            )
            raise

    @observability_runtime.span(ECONOMY_ANNUAL_STAGES.name(Stage.ECONOMY_SUBMIT))
    def _handle_create_impact(
        self,
        setup_options: EconomicImpactSetupOptions,
    ) -> EconomicImpactResult:
        baseline_policy, reform_policy = self._get_policy_jsons(
            setup_options.country_id,
            setup_options.baseline_policy_id,
            setup_options.reform_policy_id,
        )

        sim_config: SimulationOptions = self._setup_sim_options(
            setup_options,
            reform_policy=reform_policy,
            baseline_policy=baseline_policy,
            time_period=setup_options.time_period,
            include_cliffs=setup_options.target == "cliff",
        )

        sim_params = sim_config.model_dump(mode="json")
        telemetry = self._build_simulation_telemetry(
            setup_options=setup_options,
            sim_config=sim_params,
        )

        logger.log_struct(
            {
                "message": "Setting up sim API job",
                "observability_id": setup_options.observability_id,
                **setup_options.model_dump(),
            }
        )

        # Preserve execution metadata and non-identity simulation telemetry.
        sim_params["_metadata"] = {
            "reform_policy_id": setup_options.reform_policy_id,
            "baseline_policy_id": setup_options.baseline_policy_id,
            "submission_claim_id": setup_options.submission_claim_id,
            "model_version": setup_options.model_version,
            "policyengine_version": setup_options.policyengine_version,
            "data_version": setup_options.data_version,
            "dataset": setup_options.dataset,
            "resolved_app_name": setup_options.runtime_app_name,
        }
        sim_params["_telemetry"] = telemetry

        # The simulation gateway (policyengine-api-v2 PR #458) requires
        # ``time_period`` as a string, but the upstream ``policyengine``
        # package (``TimePeriodType = int``) coerces the value to int during
        # ``model_validate`` and ``model_dump`` re-emits it as int. Cast back
        # to str at the request boundary so the gateway's strict schema
        # validates instead of returning 422.
        if sim_params.get("time_period") is not None:
            sim_params["time_period"] = str(sim_params["time_period"])

        try:
            entrypoint_execution = self._simulation_gateway.run(sim_params)
        except httpx.HTTPStatusError as error:
            refusal = self._breakdown_refusal(error, breakdown=sim_config.breakdown)
            if refusal is None:
                raise
            return refusal
        try:
            execution_id = self._simulation_gateway.get_execution_id(
                entrypoint_execution
            )

            progress_log = {
                **setup_options.model_dump(),
                "message": "Sim API job started",
                "execution_id": execution_id,
                "observability_id": setup_options.observability_id,
            }
            logger.log_struct(progress_log, severity="INFO")

            self._set_reform_impact_computing(
                setup_options=setup_options,
                execution_id=execution_id,
            )
        except ReformImpactHandoffError:
            raise
        except Exception as error:
            msg = (
                "simulation was submitted but its execution state could not be "
                "handed off"
            )
            raise ReformImpactHandoffError(msg) from error

        return EconomicImpactResult.computing()

    def _with_policyengine_bundle(
        self,
        result: dict | None,
        setup_options: EconomicImpactSetupOptions,
        execution: ModalSimulationExecution | None = None,
    ) -> dict:
        result = result if isinstance(result, dict) else {}
        cached_resolved_app_name = result.get("resolved_app_name")
        use_setup_model_version = execution is not None or (
            isinstance(cached_resolved_app_name, str) and bool(cached_resolved_app_name)
        )
        bundle = {
            "model_version": (
                setup_options.model_version if use_setup_model_version else None
            ),
            "policyengine_version": (
                setup_options.policyengine_version if use_setup_model_version else None
            ),
            "data_version": setup_options.data_version,
            "dataset": setup_options.dataset,
        }
        if isinstance(result.get("policyengine_bundle"), dict):
            bundle.update(
                {
                    key: value
                    for key, value in result["policyengine_bundle"].items()
                    if value is not None
                }
            )
        execution_bundle = (
            getattr(execution, "policyengine_bundle", None)
            if execution is not None
            else None
        )
        if isinstance(execution_bundle, dict):
            bundle.update(
                {
                    key: value
                    for key, value in execution_bundle.items()
                    if value is not None
                }
            )
        response = {
            **result,
            "policyengine_bundle": bundle,
        }
        resolved_app_name = None
        if execution is not None:
            maybe_resolved_app_name = getattr(execution, "resolved_app_name", None)
            if isinstance(maybe_resolved_app_name, str) and maybe_resolved_app_name:
                resolved_app_name = maybe_resolved_app_name
        if resolved_app_name is None:
            resolved_app_name = setup_options.runtime_app_name
        if resolved_app_name:
            response["resolved_app_name"] = resolved_app_name
        return response
