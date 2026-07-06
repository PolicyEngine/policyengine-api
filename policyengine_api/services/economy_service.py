import datetime
import hashlib
import json
import uuid
from enum import Enum
from typing import Annotated, Any, Literal, Optional

import httpx
import numpy as np
from dotenv import load_dotenv
from policyengine_api.constants import (
    COUNTRY_PACKAGE_VERSIONS,
    EXECUTION_STATUSES_FAILURE,
    EXECUTION_STATUSES_PENDING,
    EXECUTION_STATUSES_SUCCESS,
    POLICYENGINE_VERSION,
    get_bundle_default_dataset,
    get_economy_impact_cache_version,
)
from policyengine_api.data.congressional_districts import (
    get_valid_congressional_districts,
    get_valid_state_codes,
    normalize_us_region,
)
from policyengine_api.data.places import validate_place_code
from policyengine_api.gcp_logging import logger
from policyengine_api.libs.simulation_api_modal import simulation_api_modal
from policyengine_api.services.budget_window_cache import BudgetWindowCache
from policyengine_api.services.policy_service import PolicyService
from policyengine_api.services.reform_impacts_service import (
    ReformImpactsService,
)
from policyengine_api.utils import budget_window as budget_window_utils
from pydantic import BaseModel, Field

load_dotenv()

policy_service = PolicyService()
reform_impacts_service = ReformImpactsService()
simulation_api = simulation_api_modal
budget_window_cache = BudgetWindowCache()


class ImpactAction(Enum):
    """
    Enum for the action to take based on the status of an economic impact calculation.
    """

    COMPLETED = "completed"
    COMPUTING = "computing"
    CREATE = "create"


class ImpactStatus(Enum):
    """
    Enum for the status of an economic impact calculation.
    """

    COMPUTING = "computing"
    OK = "ok"
    ERROR = "error"


COMPLETE_STATUSES = [ImpactStatus.OK.value, ImpactStatus.ERROR.value]
COMPUTING_STATUS = ImpactStatus.COMPUTING.value
BUDGET_WINDOW_MAX_ACTIVE_YEARS = budget_window_utils.BUDGET_WINDOW_MAX_ACTIVE_YEARS
BUDGET_WINDOW_MAX_YEARS = budget_window_utils.BUDGET_WINDOW_MAX_YEARS
BUDGET_WINDOW_MAX_END_YEAR = budget_window_utils.BUDGET_WINDOW_MAX_END_YEAR
BUDGET_WINDOW_SUBMISSION_VALIDATION_ERROR_STATUS_CODES = {400, 422}


class SimulationOptions(BaseModel):
    country: str
    scope: Literal["macro", "household"] = "macro"
    reform: dict[str, Any]
    baseline: dict[str, Any]
    time_period: str | int
    include_cliffs: bool = False
    region: str
    data: str | None = None
    model_version: str | None = None
    policyengine_version: str | None = None
    data_version: str | None = None


class EconomicImpactSetupOptions(BaseModel):
    process_id: str
    country_id: str
    reform_policy_id: int
    baseline_policy_id: int
    region: str
    dataset: str
    time_period: str
    options: dict
    api_version: str
    target: Literal["general", "cliff"]
    model_version: str | None = None
    policyengine_version: str | None = None
    data_version: str | None = None
    runtime_app_name: str | None = None
    options_hash: str | None = None


class EconomicImpactResult(BaseModel):
    """
    Model for the result of an economic impact calculation.
    Contains the status and the reform impact JSON.
    """

    status: ImpactStatus
    data: Optional[dict] = None

    model_config = {"frozen": True}  # Make model immutable

    def to_dict(self) -> dict[str, str | dict | None]:
        """
        Convert the EconomicImpactResult to a dictionary.
        """
        return {
            "status": self.status.value,
            "data": self.data,
        }

    @classmethod
    def completed(cls, data: dict) -> "EconomicImpactResult":
        """
        Create an EconomicImpactResult for a completed impact calculation.
        """
        return cls(status=ImpactStatus.OK, data=data)

    @classmethod
    def computing(cls) -> "EconomicImpactResult":
        """
        Create an EconomicImpactResult for a computing impact calculation.
        """
        return cls(status=ImpactStatus.COMPUTING, data=None)

    @classmethod
    def error(cls, message: str) -> "EconomicImpactResult":
        """
        Create an EconomicImpactResult for an error in the impact calculation.
        """
        logger.log_struct({"message": message}, severity="ERROR")
        return cls(status=ImpactStatus.ERROR, data=None)


class BudgetWindowEconomicImpactResult(BaseModel):
    """
    Model for a batch budget-window economic impact response.
    """

    status: ImpactStatus
    data: Optional[dict] = None
    progress: Optional[int] = None
    completed_years: list[str] = Field(default_factory=list)
    computing_years: list[str] = Field(default_factory=list)
    queued_years: list[str] = Field(default_factory=list)
    message: Optional[str] = None
    error: Optional[str] = None
    cache_status: Optional[str] = None

    model_config = {"frozen": True}

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "data": self.data,
            "progress": self.progress,
            "completed_years": self.completed_years,
            "computing_years": self.computing_years,
            "queued_years": self.queued_years,
            "message": self.message,
            "error": self.error,
        }

    @classmethod
    def completed(
        cls, data: dict, *, cache_status: Optional[str] = None
    ) -> "BudgetWindowEconomicImpactResult":
        return cls(
            status=ImpactStatus.OK,
            data=data,
            progress=100,
            cache_status=cache_status,
        )

    @classmethod
    def computing(
        cls,
        *,
        progress: int,
        completed_years: list[str],
        computing_years: list[str],
        queued_years: list[str],
        message: str,
        cache_status: Optional[str] = None,
    ) -> "BudgetWindowEconomicImpactResult":
        return cls(
            status=ImpactStatus.COMPUTING,
            data=None,
            progress=progress,
            completed_years=completed_years,
            computing_years=computing_years,
            queued_years=queued_years,
            message=message,
            cache_status=cache_status,
        )

    @classmethod
    def failed(
        cls,
        message: str,
        *,
        completed_years: Optional[list[str]] = None,
        computing_years: Optional[list[str]] = None,
        queued_years: Optional[list[str]] = None,
        cache_status: Optional[str] = None,
    ) -> "BudgetWindowEconomicImpactResult":
        logger.log_struct({"message": message}, severity="ERROR")
        return cls(
            status=ImpactStatus.ERROR,
            data=None,
            completed_years=completed_years or [],
            computing_years=computing_years or [],
            queued_years=queued_years or [],
            message=message,
            error=message,
            cache_status=cache_status,
        )


class EconomyService:
    """
    Service for calculating economic impact of policy reforms; this is connected
    to the /economy route, which does not have its own table; therefore, it connects
    with other services to access their respective tables
    """

    def get_economic_impact(
        self,
        country_id: str,
        policy_id: int,
        baseline_policy_id: int,
        region: str,
        dataset: str,
        time_period: str,
        options: dict,
        api_version: str,
        target: Literal["general", "cliff"] = "general",
    ) -> EconomicImpactResult:
        """
        Calculate the society-wide economic impact of a policy reform.

        Returns a tuple of:
        - status: "ok", "error", or "computing"
        - reform_impact_json: The JSON object containing the economic impact data, or None if
          the status is "computing" or "error".
        """

        try:
            # Normalize region early for US; this allows us to accommodate legacy
            # regions that don't contain a region prefix.
            if country_id == "us":
                region = normalize_us_region(region)

            economic_impact_setup_options = self._build_economic_impact_setup_options(
                country_id=country_id,
                policy_id=policy_id,
                baseline_policy_id=baseline_policy_id,
                region=region,
                dataset=dataset,
                time_period=time_period,
                options=options,
                api_version=api_version,
                target=target,
            )

            return self._get_or_create_economic_impact(
                setup_options=economic_impact_setup_options,
            )

        except Exception as e:
            print(f"Error getting economic impact: {str(e)}")
            raise e

    def get_budget_window_economic_impact(
        self,
        country_id: str,
        policy_id: int,
        baseline_policy_id: int,
        region: str,
        dataset: str,
        start_year: str,
        window_size: int,
        options: dict,
        api_version: str,
        target: Literal["general", "cliff"] = "general",
        max_active_years: int = BUDGET_WINDOW_MAX_ACTIVE_YEARS,
    ) -> BudgetWindowEconomicImpactResult:
        try:
            if country_id == "us":
                region = normalize_us_region(region)

            budget_window_setup = budget_window_utils.build_budget_window_request_setup(
                start_year=start_year,
                window_size=window_size,
                target=target,
            )
            start_year = budget_window_setup.start_year
            years = budget_window_setup.years
            setup_options = self._build_economic_impact_setup_options(
                country_id=country_id,
                policy_id=policy_id,
                baseline_policy_id=baseline_policy_id,
                region=region,
                dataset=dataset,
                time_period=budget_window_setup.time_period,
                options=dict(options),
                api_version=api_version,
                target=target,
            )
            cache_key = self._build_budget_window_cache_key(setup_options)

            cached_result = budget_window_cache.get_completed_result(cache_key)
            if cached_result is not None:
                return BudgetWindowEconomicImpactResult.completed(
                    cached_result,
                    cache_status="result-hit",
                )

            batch_job_id = budget_window_cache.get_batch_job_id(cache_key)
            if batch_job_id:
                return self._get_budget_window_result_from_batch_job_id(
                    batch_job_id=batch_job_id,
                    cache_key=cache_key,
                    total_years=len(years),
                    queued_years_on_submit=years,
                    cache_status="batch-id-hit",
                )

            claim_token = setup_options.process_id
            cache_status = "starting-claim-hit"
            if budget_window_cache.claim_batch_start(cache_key, claim_token):
                cache_status = "miss"
                try:
                    batch_execution = self._start_budget_window_batch(
                        setup_options=setup_options,
                        start_year=start_year,
                        window_size=window_size,
                        max_parallel=max_active_years,
                    )
                    budget_window_cache.store_batch_job_id(
                        cache_key, batch_execution.batch_job_id
                    )
                except httpx.HTTPStatusError as error:
                    budget_window_cache.clear_starting_claim(cache_key, claim_token)
                    if (
                        error.response.status_code
                        in BUDGET_WINDOW_SUBMISSION_VALIDATION_ERROR_STATUS_CODES
                    ):
                        return BudgetWindowEconomicImpactResult.failed(
                            self._build_budget_window_submission_error_message(error),
                            queued_years=years,
                            cache_status=cache_status,
                        )
                    raise
                except Exception:
                    budget_window_cache.clear_starting_claim(cache_key, claim_token)
                    raise

            return self._build_budget_window_computing_result(
                total_years=len(years),
                completed_years=[],
                computing_years=[],
                queued_years=years,
                progress=0,
                cache_status=cache_status,
            )
        except Exception as e:
            print(f"Error getting budget-window economic impact: {str(e)}")
            raise e

    def _build_budget_window_cache_key(
        self,
        setup_options: EconomicImpactSetupOptions,
    ) -> str:
        return budget_window_cache.build_key(
            country_id=setup_options.country_id,
            reform_policy_id=setup_options.reform_policy_id,
            baseline_policy_id=setup_options.baseline_policy_id,
            region=setup_options.region,
            dataset=setup_options.dataset,
            time_period=setup_options.time_period,
            options_hash=setup_options.options_hash,
            api_version=setup_options.api_version,
        )

    def _build_budget_window_batch_payload(
        self,
        *,
        setup_options: EconomicImpactSetupOptions,
        start_year: str,
        window_size: int,
        max_parallel: int,
    ) -> dict[str, Any]:
        baseline_policy = policy_service.get_policy_json(
            setup_options.country_id,
            setup_options.baseline_policy_id,
        )
        reform_policy = policy_service.get_policy_json(
            setup_options.country_id,
            setup_options.reform_policy_id,
        )
        sim_config: SimulationOptions = self._setup_sim_options(
            country_id=setup_options.country_id,
            reform_policy=reform_policy,
            baseline_policy=baseline_policy,
            region=setup_options.region,
            time_period=start_year,
            dataset=setup_options.dataset,
            scope="macro",
            include_cliffs=False,
            model_version=setup_options.model_version,
            policyengine_version=setup_options.policyengine_version,
            data_version=setup_options.data_version,
        )
        sim_params = sim_config.model_dump()
        sim_params.pop("time_period", None)
        sim_params["start_year"] = start_year
        sim_params["window_size"] = window_size
        sim_params["max_parallel"] = max_parallel
        sim_params["target"] = setup_options.target
        return sim_params

    def _start_budget_window_batch(
        self,
        *,
        setup_options: EconomicImpactSetupOptions,
        start_year: str,
        window_size: int,
        max_parallel: int,
    ):
        sim_params = self._build_budget_window_batch_payload(
            setup_options=setup_options,
            start_year=start_year,
            window_size=window_size,
            max_parallel=max_parallel,
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

        return simulation_api.run_budget_window_batch(sim_params)

    def _build_budget_window_submission_error_message(
        self, error: httpx.HTTPStatusError
    ) -> str:
        try:
            response_json = error.response.json()
        except ValueError:
            response_json = None

        if isinstance(response_json, dict):
            for key in ("detail", "message", "error"):
                value = response_json.get(key)
                if value:
                    return str(value)

        response_text = error.response.text.strip()
        if response_text:
            return response_text

        return str(error)

    def _get_budget_window_result_from_batch_job_id(
        self,
        *,
        batch_job_id: str,
        cache_key: str,
        total_years: int,
        queued_years_on_submit: list[str],
        cache_status: Optional[str] = None,
    ) -> BudgetWindowEconomicImpactResult:
        batch_execution = simulation_api.get_budget_window_batch_by_id(batch_job_id)

        if batch_execution.status in EXECUTION_STATUSES_SUCCESS:
            result = batch_execution.result
            if not isinstance(result, dict) or not result:
                budget_window_cache.clear_batch_job_id(cache_key)
                return BudgetWindowEconomicImpactResult.failed(
                    "Budget-window batch completed without a result",
                    completed_years=batch_execution.completed_years,
                    computing_years=batch_execution.running_years,
                    queued_years=batch_execution.queued_years or queued_years_on_submit,
                    cache_status=cache_status,
                )
            budget_window_cache.set_completed_result(cache_key, result)
            budget_window_cache.clear_batch_job_id(cache_key)
            return BudgetWindowEconomicImpactResult.completed(
                result,
                cache_status=cache_status,
            )

        if batch_execution.status in EXECUTION_STATUSES_FAILURE:
            error_message = batch_execution.error or "Budget-window batch failed"
            budget_window_cache.clear_batch_job_id(cache_key)
            return BudgetWindowEconomicImpactResult.failed(
                error_message,
                completed_years=batch_execution.completed_years,
                computing_years=batch_execution.running_years,
                queued_years=batch_execution.queued_years or queued_years_on_submit,
                cache_status=cache_status,
            )

        if batch_execution.status in EXECUTION_STATUSES_PENDING:
            return self._build_budget_window_computing_result(
                total_years=total_years,
                completed_years=batch_execution.completed_years,
                computing_years=batch_execution.running_years,
                queued_years=batch_execution.queued_years,
                progress=batch_execution.progress,
                cache_status=cache_status,
            )

        raise ValueError(
            f"Unexpected budget-window batch execution state: {batch_execution.status}"
        )

    def _build_budget_window_computing_result(
        self,
        *,
        total_years: int,
        completed_years: list[str],
        computing_years: list[str],
        queued_years: list[str],
        progress: Optional[int] = None,
        cache_status: Optional[str] = None,
    ) -> BudgetWindowEconomicImpactResult:
        resolved_progress = progress
        if resolved_progress is None:
            resolved_progress = round((len(completed_years) / total_years) * 100)

        return BudgetWindowEconomicImpactResult.computing(
            progress=resolved_progress,
            completed_years=completed_years,
            computing_years=computing_years,
            queued_years=queued_years,
            message=self._build_budget_window_progress_message(
                completed_years=completed_years,
                total_years=total_years,
                computing_years=computing_years,
                queued_years=queued_years,
            ),
            cache_status=cache_status,
        )

    def _build_economic_impact_setup_options(
        self,
        *,
        country_id: str,
        policy_id: int,
        baseline_policy_id: int,
        region: str,
        dataset: str,
        time_period: str,
        options: dict,
        api_version: str,
        target: Literal["general", "cliff"] = "general",
    ) -> EconomicImpactSetupOptions:
        process_id: str = self._create_process_id()
        cache_version = get_economy_impact_cache_version(country_id, api_version)
        country_package_version = COUNTRY_PACKAGE_VERSIONS.get(country_id)
        resolved_dataset = self._canonical_dataset(country_id, dataset)
        resolved_data_version = self._extract_dataset_version(resolved_dataset)
        policyengine_version = (
            POLICYENGINE_VERSION if country_id in {"us", "uk"} else None
        )
        options_hash = self._build_options_hash(
            options=options,
            model_version=country_package_version,
            dataset=resolved_dataset,
            data_version=resolved_data_version,
            policyengine_version=policyengine_version,
        )

        return EconomicImpactSetupOptions.model_validate(
            {
                "process_id": process_id,
                "country_id": country_id,
                "reform_policy_id": policy_id,
                "baseline_policy_id": baseline_policy_id,
                "region": region,
                "dataset": resolved_dataset,
                "time_period": time_period,
                "options": options,
                "api_version": cache_version,
                "target": target,
                "model_version": country_package_version,
                "policyengine_version": policyengine_version,
                "data_version": resolved_data_version,
                "runtime_app_name": None,
                "options_hash": options_hash,
            }
        )

    def _get_or_create_economic_impact(
        self, setup_options: EconomicImpactSetupOptions
    ) -> EconomicImpactResult:
        logger.log_struct(
            {
                "message": "Received request for economic impact; checking if already in reform_impacts table",
                **setup_options.model_dump(),
            },
            severity="INFO",
        )

        most_recent_impact: dict | None = self._get_most_recent_impact(
            setup_options=setup_options
        )

        if most_recent_impact and self._should_refresh_cached_impact(
            setup_options=setup_options,
            most_recent_impact=most_recent_impact,
        ):
            most_recent_impact = self._get_most_recent_impact(setup_options)
            if (
                not most_recent_impact
                or most_recent_impact.get("options_hash") != setup_options.options_hash
            ):
                most_recent_impact = None

        impact_action: ImpactAction = self._determine_impact_action(
            most_recent_impact=most_recent_impact
        )

        if impact_action == ImpactAction.COMPLETED:
            logger.log_struct(
                {
                    "message": "Found completed economic impact in db; returning result",
                    **setup_options.model_dump(),
                },
                severity="INFO",
            )
            return self._handle_completed_impact(
                setup_options=setup_options,
                most_recent_impact=most_recent_impact,
            )

        if impact_action == ImpactAction.COMPUTING:
            logger.log_struct(
                {
                    "message": "Found computing economic impact record in db; confirming this is still computing",
                    **setup_options.model_dump(),
                },
                severity="INFO",
            )
            return self._handle_computing_impact(
                setup_options=setup_options,
                most_recent_impact=most_recent_impact,
            )

        if impact_action == ImpactAction.CREATE:
            self._resolve_runtime_bundle_for_setup_options(setup_options)
            logger.log_struct(
                {
                    "message": "No previous economic impact record found in db; creating new simulation run",
                    **setup_options.model_dump(),
                },
                severity="INFO",
            )
            return self._handle_create_impact(
                setup_options=setup_options,
            )

        raise ValueError(f"Unexpected impact action: {impact_action}")

    def _resolve_runtime_bundle_for_setup_options(
        self,
        setup_options: EconomicImpactSetupOptions,
    ) -> None:
        if setup_options.runtime_app_name is None:
            (
                setup_options.runtime_app_name,
                setup_options.model_version,
            ) = simulation_api.resolve_app_name(
                setup_options.country_id,
                setup_options.model_version,
                policyengine_version=setup_options.policyengine_version,
            )

        setup_options.options_hash = self._build_options_hash(
            options=setup_options.options,
            model_version=setup_options.model_version,
            dataset=setup_options.dataset,
            data_version=setup_options.data_version,
            policyengine_version=setup_options.policyengine_version,
            runtime_app_name=setup_options.runtime_app_name,
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
            active_years = ", ".join(computing_years[:2])
            if len(computing_years) > 2:
                active_years = f"{active_years} + {len(computing_years) - 2} more"
            return f"Scoring {active_years} ({completed_count} of {total_years} complete)..."

        if queued_years:
            return f"Queued {queued_years[0]} ({completed_count} of {total_years} complete)..."

        return f"Scoring budget window ({completed_count} of {total_years} complete)..."

    def _get_previous_impacts(
        self,
        country_id: str,
        policy_id: int,
        baseline_policy_id: int,
        region: str,
        dataset: str,
        time_period: str,
        options_hash: str,
        api_version: str,
    ):
        """
        Fetch any previous simulation runs for the given policy reform.
        """

        previous_impacts: list[Any] = (
            reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix(
                country_id,
                policy_id,
                baseline_policy_id,
                region,
                dataset,
                time_period,
                options_hash,
                self._build_options_hash_lookup_pattern(options_hash),
                api_version,
            )
        )
        return previous_impacts

    def _get_most_recent_impact(
        self,
        setup_options: EconomicImpactSetupOptions,
    ) -> dict | None:
        """
        Get the first impact from the reform_impacts table based on the provided setup options.
        Returns the first impact if it exists, otherwise returns None.
        """
        previous_impacts = self._get_previous_impacts(
            country_id=setup_options.country_id,
            policy_id=setup_options.reform_policy_id,
            baseline_policy_id=setup_options.baseline_policy_id,
            region=setup_options.region,
            dataset=setup_options.dataset,
            time_period=setup_options.time_period,
            options_hash=setup_options.options_hash,
            api_version=setup_options.api_version,
        )

        if not previous_impacts:
            return None

        for impact in previous_impacts:
            if impact.get("options_hash") == setup_options.options_hash:
                return impact

        return previous_impacts[0]

    def _determine_impact_action(
        self,
        most_recent_impact: dict | None,
    ) -> ImpactAction:
        if not most_recent_impact:
            return ImpactAction.CREATE

        status = most_recent_impact.get("status")
        if status in [ImpactStatus.OK.value, ImpactStatus.ERROR.value]:
            return ImpactAction.COMPLETED
        elif status == ImpactStatus.COMPUTING.value:
            return ImpactAction.COMPUTING
        else:
            raise ValueError(f"Unknown impact status: {status}")

    def _handle_execution_state(
        self,
        setup_options: EconomicImpactSetupOptions,
        execution_state: str,
        reform_impact: dict,
        execution: Optional[Any] = None,
    ) -> EconomicImpactResult:
        """
        Handle the state of the execution and return the appropriate status and result.

        Supports both GCP Workflow statuses (SUCCEEDED, FAILED, ACTIVE) and
        Modal statuses (complete, failed, running, submitted).
        """
        if execution_state in EXECUTION_STATUSES_SUCCESS:
            result = self._with_policyengine_bundle(
                result=simulation_api.get_execution_result(execution),
                setup_options=setup_options,
                execution=execution,
            )
            self._set_reform_impact_complete(
                setup_options=setup_options,
                reform_impact_json=json.dumps(result),
                execution_id=reform_impact["execution_id"],
            )
            logger.log_struct(
                {"message": "Sim API execution completed"},
                severity="INFO",
            )
            return EconomicImpactResult.completed(data=result)

        elif execution_state in EXECUTION_STATUSES_FAILURE:
            # For Modal, try to get error message from execution
            error_message = "Simulation API execution failed"
            if (
                execution is not None
                and hasattr(execution, "error")
                and execution.error
            ):
                error_message = f"Simulation API execution failed: {execution.error}"

            self._set_reform_impact_error(
                setup_options=setup_options,
                message=error_message,
                execution_id=reform_impact["execution_id"],
            )
            logger.log_struct(
                {"message": error_message},
                severity="ERROR",
            )
            return EconomicImpactResult.error(message=error_message)

        elif execution_state in EXECUTION_STATUSES_PENDING:
            logger.log_struct(
                {"message": "Sim API execution is still running"},
                severity="INFO",
            )
            return EconomicImpactResult.computing()

        else:
            raise ValueError(f"Unexpected sim API execution state: {execution_state}")

    def _handle_completed_impact(
        self,
        setup_options: EconomicImpactSetupOptions,
        most_recent_impact: dict,
    ) -> EconomicImpactResult:
        result = json.loads(most_recent_impact["reform_impact_json"])
        return EconomicImpactResult.completed(
            data=self._with_policyengine_bundle(
                result=result,
                setup_options=setup_options,
            )
        )

    def _handle_computing_impact(
        self,
        setup_options: EconomicImpactSetupOptions,
        most_recent_impact: dict,
    ) -> EconomicImpactResult:
        execution = simulation_api.get_execution_by_id(
            most_recent_impact["execution_id"]
        )
        execution_state = simulation_api.get_execution_status(execution)
        return self._handle_execution_state(
            execution_state=execution_state,
            setup_options=setup_options,
            reform_impact=most_recent_impact,
            execution=execution,
        )

    def _handle_create_impact(
        self,
        setup_options: EconomicImpactSetupOptions,
    ) -> EconomicImpactResult:
        baseline_policy = policy_service.get_policy_json(
            setup_options.country_id, setup_options.baseline_policy_id
        )
        reform_policy = policy_service.get_policy_json(
            setup_options.country_id, setup_options.reform_policy_id
        )

        sim_config: SimulationOptions = self._setup_sim_options(
            country_id=setup_options.country_id,
            reform_policy=reform_policy,
            baseline_policy=baseline_policy,
            region=setup_options.region,
            time_period=setup_options.time_period,
            dataset=setup_options.dataset,
            scope="macro",
            include_cliffs=setup_options.target == "cliff",
            model_version=setup_options.model_version,
            data_version=setup_options.data_version,
            policyengine_version=setup_options.policyengine_version,
        )

        sim_params = sim_config.model_dump(mode="json")
        telemetry = self._build_simulation_telemetry(
            setup_options=setup_options,
            sim_config=sim_params,
        )

        logger.log_struct(
            {
                "message": "Setting up sim API job",
                "run_id": telemetry["run_id"],
                **setup_options.model_dump(),
            }
        )

        # Preserve both legacy metadata and the new telemetry envelope.
        sim_params["_metadata"] = {
            "reform_policy_id": setup_options.reform_policy_id,
            "baseline_policy_id": setup_options.baseline_policy_id,
            "process_id": setup_options.process_id,
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

        sim_api_execution = simulation_api.run(sim_params)
        execution_id = simulation_api.get_execution_id(sim_api_execution)

        run_id = getattr(sim_api_execution, "run_id", None) or telemetry["run_id"]

        progress_log = {
            **setup_options.model_dump(),
            "message": "Sim API job started",
            "execution_id": execution_id,
            "run_id": run_id,
        }
        logger.log_struct(progress_log, severity="INFO")

        self._set_reform_impact_computing(
            setup_options=setup_options,
            execution_id=execution_id,
        )

        return EconomicImpactResult.computing()

    def _setup_sim_options(
        self,
        country_id: str,
        reform_policy: Annotated[str, "String-formatted JSON"],
        baseline_policy: Annotated[str, "String-formatted JSON"],
        region: str,
        time_period: str,
        scope: Literal["macro", "household"] = "macro",
        include_cliffs: bool = False,
        model_version: str | None = None,
        policyengine_version: str | None = None,
        data_version: str | None = None,
        dataset: str = "default",
    ) -> SimulationOptions:
        """
        Set up the simulation options for the simulation API job.
        """

        return SimulationOptions.model_validate(
            {
                "country": country_id,
                "scope": scope,
                "reform": json.loads(reform_policy),
                "baseline": json.loads(baseline_policy),
                "time_period": time_period,
                "include_cliffs": include_cliffs,
                "region": self._setup_region(country_id=country_id, region=region),
                "data": self._setup_data(
                    country_id=country_id, region=region, dataset=dataset
                ),
                "model_version": model_version,
                "policyengine_version": policyengine_version,
                "data_version": data_version,
            }
        )

    def _build_options_hash(
        self,
        options: dict,
        model_version: str | None,
        dataset: str,
        runtime_app_name: str | None = None,
        data_version: str | None = None,
        policyengine_version: str | None = None,
    ) -> str:
        option_pairs = "&".join(f"{key}={options[key]}" for key in sorted(options))
        bundle_parts = [
            f"dataset={dataset}",
            f"model_version={model_version}",
        ]
        if data_version:
            bundle_parts.append(f"data_version={data_version}")
        if policyengine_version:
            bundle_parts.append(f"policyengine_version={policyengine_version}")
        if runtime_app_name:
            bundle_parts.append(f"runtime_app_name={runtime_app_name}")
        return "[" + "&".join([option_pairs, *bundle_parts]).strip("&") + "]"

    def _build_options_hash_lookup_pattern(self, options_hash: str) -> str:
        escaped_options_hash = (
            options_hash.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        if options_hash.endswith("]"):
            return f"{escaped_options_hash[:-1]}&%"
        return f"{escaped_options_hash}%"

    def _extract_dataset_version(self, dataset: str | None) -> str | None:
        if dataset is None:
            return None
        if "@" not in dataset:
            return None
        return dataset.rsplit("@", 1)[1]

    def _extract_cached_result(self, most_recent_impact: dict) -> dict:
        try:
            return json.loads(most_recent_impact["reform_impact_json"])
        except (TypeError, ValueError):
            return {}

    def _should_refresh_cached_impact(
        self,
        setup_options: EconomicImpactSetupOptions,
        most_recent_impact: dict,
    ) -> bool:
        if most_recent_impact.get("status") == ImpactStatus.COMPUTING.value:
            return False

        cached_result = self._extract_cached_result(most_recent_impact)
        cached_resolved_app_name = cached_result.get("resolved_app_name")
        try:
            runtime_app_name, resolved_model_version = simulation_api.resolve_app_name(
                setup_options.country_id,
                setup_options.model_version,
                policyengine_version=setup_options.policyengine_version,
            )
        except Exception:
            return False

        setup_options.runtime_app_name = runtime_app_name
        setup_options.model_version = resolved_model_version
        setup_options.options_hash = self._build_options_hash(
            options=setup_options.options,
            model_version=resolved_model_version,
            dataset=setup_options.dataset,
            data_version=setup_options.data_version,
            policyengine_version=setup_options.policyengine_version,
            runtime_app_name=runtime_app_name,
        )
        if (
            not isinstance(cached_resolved_app_name, str)
            or not cached_resolved_app_name
        ):
            return True

        return runtime_app_name != cached_resolved_app_name

    def _with_policyengine_bundle(
        self,
        result: dict,
        setup_options: EconomicImpactSetupOptions,
        execution: Optional[Any] = None,
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
            for key, value in result["policyengine_bundle"].items():
                if value is not None:
                    bundle[key] = value
        execution_bundle = (
            getattr(execution, "policyengine_bundle", None)
            if execution is not None
            else None
        )
        if isinstance(execution_bundle, dict):
            for key, value in execution_bundle.items():
                if value is not None:
                    bundle[key] = value
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

    def _setup_region(self, country_id: str, region: str) -> str:
        """
        Validate the region for the given country.

        Assumes region has already been normalized (e.g., "ca" -> "state/ca").
        Raises ValueError for invalid regions.
        """

        # For US regions, validate (skip validation for national "us")
        if country_id == "us" and region != "us":
            self._validate_us_region(region)

        return region

    def _validate_us_region(self, region: str) -> None:
        """
        Validate a prefixed US region string.

        Raises ValueError if the region is not valid.
        """
        if region.startswith("state/"):
            state_code = region[len("state/") :]
            if state_code.lower() not in get_valid_state_codes():
                raise ValueError(f"Invalid US state: '{state_code}'")
        elif region.startswith("place/"):
            place_code = region[len("place/") :]
            validate_place_code(place_code)
        elif region.startswith("congressional_district/"):
            district_id = region[len("congressional_district/") :]
            if district_id.lower() not in get_valid_congressional_districts():
                raise ValueError(f"Invalid congressional district: '{district_id}'")
        else:
            raise ValueError(f"Invalid US region: '{region}'")

    # Deprecated dataset aliases accepted for older app-v2 callers. These no
    # longer route to special sim API datasets.
    DEPRECATED_BREAKDOWN_DATASETS = {
        "national-with-breakdowns",
        "national-with-breakdowns-test",
        "national-with-datasets",
    }
    DEPRECATED_DATASETS_BY_COUNTRY = {
        "us": {"cps", "enhanced_cps"},
        "uk": {"enhanced_frs"},
    }

    def _canonical_dataset(
        self, country_id: str, dataset: str | None = "default"
    ) -> str:
        if not dataset:
            return "default"
        if dataset in self.DEPRECATED_BREAKDOWN_DATASETS:
            return "default"
        if dataset == get_bundle_default_dataset(country_id):
            return "default"
        return dataset

    def _setup_data(
        self, country_id: str, region: str, dataset: str = "default"
    ) -> str | None:
        """
        Determine the dataset value to send to the simulation gateway.

        Default requests intentionally omit ``data`` so the gateway resolves
        the certified dataset from the requested .py bundle. Explicit dataset
        values are retained as a legacy escape hatch for callers that still pass
        dataset designators or full dataset URIs.
        """
        if dataset in (None, "", "default"):
            return None
        if dataset in self.DEPRECATED_BREAKDOWN_DATASETS:
            return None

        deprecated_datasets = self.DEPRECATED_DATASETS_BY_COUNTRY.get(country_id, set())
        if dataset in deprecated_datasets:
            raise ValueError(
                f"Dataset '{dataset}' is deprecated. Omit dataset to use the "
                "certified PolicyEngine bundle dataset, or pass a full dataset URI."
            )

        if dataset == get_bundle_default_dataset(country_id):
            return None

        if "://" in dataset:
            return dataset

        return dataset

    def _build_simulation_telemetry(
        self,
        setup_options: EconomicImpactSetupOptions,
        sim_config: dict[str, Any],
    ) -> dict[str, Any]:
        simulation_kind, geography_type, geography_code = (
            self._classify_simulation_geography(
                country_id=setup_options.country_id,
                region=setup_options.region,
            )
        )

        return {
            "run_id": str(uuid.uuid4()),
            "process_id": setup_options.process_id,
            "traceparent": self._get_current_traceparent(),
            "requested_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "simulation_kind": simulation_kind,
            "geography_code": geography_code,
            "geography_type": geography_type,
            "config_hash": self._stable_config_hash(sim_config),
            "capture_mode": "disabled",
        }

    def _classify_simulation_geography(
        self,
        country_id: str,
        region: str,
    ) -> tuple[str, str, str]:
        if region == country_id:
            return "national", "national", country_id

        if "/" not in region:
            return "other", "other", region

        geography_type, geography_code = region.split("/", maxsplit=1)
        simulation_kind = (
            "district" if geography_type == "congressional_district" else geography_type
        )
        return simulation_kind, geography_type, geography_code

    def _stable_config_hash(self, payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    def _get_current_traceparent(self) -> str | None:
        try:
            from opentelemetry import trace
        except Exception:
            return None

        span = trace.get_current_span()
        span_context = span.get_span_context()
        if not getattr(span_context, "is_valid", False):
            return None

        trace_flags = int(getattr(span_context, "trace_flags", 0))
        return (
            f"00-{span_context.trace_id:032x}-"
            f"{span_context.span_id:016x}-{trace_flags:02x}"
        )

    # Note: The following methods that interface with the ReformImpactsService
    # are written separately because the service relies upon mutating an original
    # 'computing' record to 'ok' or 'error' status, rather than creating a new record.
    # This should be addressed in the future.
    def _set_reform_impact_computing(
        self,
        setup_options: EconomicImpactSetupOptions,
        execution_id: str,
    ):
        """
        In the reform_impact table, set the status of the impact to "computing".
        """
        try:
            reform_impacts_service.set_reform_impact(
                country_id=setup_options.country_id,
                policy_id=setup_options.reform_policy_id,
                baseline_policy_id=setup_options.baseline_policy_id,
                region=setup_options.region,
                dataset=setup_options.dataset,
                time_period=setup_options.time_period,
                options=json.dumps(setup_options.options),
                options_hash=setup_options.options_hash,
                status=ImpactStatus.COMPUTING.value,
                api_version=setup_options.api_version,
                reform_impact_json=json.dumps({}),
                start_time=datetime.datetime.now(),
                execution_id=execution_id,
            )
        except Exception as e:
            logger.log_struct(
                {
                    "message": f"Error inserting computing record: {str(e)}",
                    **setup_options.model_dump(),
                }
            )
            raise e

    def _set_reform_impact_complete(
        self,
        setup_options: EconomicImpactSetupOptions,
        reform_impact_json: str,
        execution_id: str,
    ):
        """
        In the reform_impact table, set the status of the impact to "ok" and store the reform impact JSON.
        """
        try:
            reform_impacts_service.set_complete_reform_impact(
                country_id=setup_options.country_id,
                reform_policy_id=setup_options.reform_policy_id,
                baseline_policy_id=setup_options.baseline_policy_id,
                region=setup_options.region,
                dataset=setup_options.dataset,
                time_period=setup_options.time_period,
                options_hash=setup_options.options_hash,
                reform_impact_json=reform_impact_json,
                execution_id=execution_id,
            )
        except Exception as e:
            logger.log_struct(
                {
                    "message": f"Error setting completed reform impact record: {str(e)}",
                    **setup_options.model_dump(),
                }
            )
            raise e

    def _set_reform_impact_error(
        self,
        setup_options: EconomicImpactSetupOptions,
        message: str,
        execution_id: str,
    ):
        """
        In the reform_impact table, set the status of the impact to "error" and store the error message.
        """
        try:
            reform_impacts_service.set_error_reform_impact(
                country_id=setup_options.country_id,
                policy_id=setup_options.reform_policy_id,
                baseline_policy_id=setup_options.baseline_policy_id,
                region=setup_options.region,
                dataset=setup_options.dataset,
                time_period=setup_options.time_period,
                options_hash=setup_options.options_hash,
                message=message,
                execution_id=execution_id,
            )
        except Exception as e:
            logger.log_struct(
                {
                    "message": f"Error setting error reform impact record: {str(e)}",
                    **setup_options.model_dump(),
                }
            )
            raise e

    def _create_process_id(self) -> str:
        """
        Generate a unique process ID based on the current timestamp and a random number.
        This is used to track the process in the database and logs.
        """
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        random_number = np.random.randint(1000, 9999)
        return f"job_{timestamp}_{random_number}"
