from policyengine_api.services.policy_service import PolicyService
from policyengine_api.services.reform_impacts_service import (
    ReformImpactsService,
)
from policyengine_api.constants import (
    COUNTRY_PACKAGE_VERSIONS,
    EXECUTION_STATUSES_SUCCESS,
    EXECUTION_STATUSES_FAILURE,
    EXECUTION_STATUSES_PENDING,
    get_economy_impact_cache_version,
)
from policyengine_api.gcp_logging import logger
from policyengine_api.libs.simulation_api_modal import simulation_api_modal
from policyengine_api.data.model_setup import (
    datasets as configured_datasets,
)
from policyengine_api.data.congressional_districts import (
    get_valid_state_codes,
    get_valid_congressional_districts,
    normalize_us_region,
)
from policyengine_api.data.places import validate_place_code
from policyengine.simulation import SimulationOptions
from policyengine.utils.data.datasets import get_default_dataset
import json
import datetime
import hashlib
import uuid
from typing import Literal, Any, Optional, Annotated
from dotenv import load_dotenv
from pydantic import BaseModel
import numpy as np
from enum import Enum

load_dotenv()

policy_service = PolicyService()
reform_impacts_service = ReformImpactsService()
simulation_api = simulation_api_modal


def get_policyengine_version() -> str | None:
    """Legacy test seam; runtime bundle metadata comes from the simulation API."""
    return None


def get_dataset_version(country_id: str) -> str | None:
    """Legacy test seam; runtime bundle metadata comes from the simulation API."""
    return None


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

            # Set up logging
            process_id: str = self._create_process_id()

            country_package_version = COUNTRY_PACKAGE_VERSIONS.get(country_id)
            cache_version = get_economy_impact_cache_version(country_id, api_version)
            resolved_dataset = self._setup_data(
                country_id=country_id,
                region=region,
                dataset=dataset,
            )
            resolved_model_version = country_package_version
            resolved_data_version = self._extract_dataset_version(resolved_dataset)
            options_hash = self._build_options_hash(
                options=options,
                model_version=resolved_model_version,
                dataset=resolved_dataset,
            )

            economic_impact_setup_options = EconomicImpactSetupOptions.model_validate(
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
                    "model_version": resolved_model_version,
                    "policyengine_version": None,
                    "data_version": resolved_data_version,
                    "runtime_app_name": None,
                    "options_hash": options_hash,
                }
            )

            # Logging that we've received a request
            logger.log_struct(
                {
                    "message": "Received request for economic impact; checking if already in reform_impacts table",
                    **economic_impact_setup_options.model_dump(),
                },
                severity="INFO",
            )

            most_recent_impact: dict | None = self._get_most_recent_impact(
                setup_options=economic_impact_setup_options,
            )

            if most_recent_impact and self._should_refresh_cached_impact(
                setup_options=economic_impact_setup_options,
                most_recent_impact=most_recent_impact,
            ):
                most_recent_impact = self._get_most_recent_impact(
                    economic_impact_setup_options
                )
                if (
                    not most_recent_impact
                    or most_recent_impact.get("options_hash")
                    != economic_impact_setup_options.options_hash
                ):
                    most_recent_impact = None

            impact_action: ImpactAction = self._determine_impact_action(
                most_recent_impact=most_recent_impact,
            )

            if impact_action == ImpactAction.COMPLETED:
                logger.log_struct(
                    {
                        "message": "Found completed economic impact in db; returning result",
                        **economic_impact_setup_options.model_dump(),
                    },
                    severity="INFO",
                )
                return self._handle_completed_impact(
                    setup_options=economic_impact_setup_options,
                    most_recent_impact=most_recent_impact,
                )

            if impact_action == ImpactAction.COMPUTING:
                logger.log_struct(
                    {
                        "message": "Found computing economic impact record in db; confirming this is still computing",
                        **economic_impact_setup_options.model_dump(),
                    },
                    severity="INFO",
                )
                return self._handle_computing_impact(
                    setup_options=economic_impact_setup_options,
                    most_recent_impact=most_recent_impact,
                )

            if impact_action == ImpactAction.CREATE:
                if economic_impact_setup_options.runtime_app_name is None:
                    (
                        economic_impact_setup_options.runtime_app_name,
                        economic_impact_setup_options.model_version,
                    ) = simulation_api.resolve_app_name(
                        country_id,
                        economic_impact_setup_options.model_version,
                    )
                    economic_impact_setup_options.options_hash = self._build_options_hash(
                        options=options,
                        model_version=economic_impact_setup_options.model_version,
                        dataset=resolved_dataset,
                        data_version=resolved_data_version,
                        runtime_app_name=economic_impact_setup_options.runtime_app_name,
                    )
                logger.log_struct(
                    {
                        "message": "No previous economic impact record found in db; creating new simulation run",
                        **economic_impact_setup_options.model_dump(),
                    },
                    severity="INFO",
                )
                return self._handle_create_impact(
                    setup_options=economic_impact_setup_options,
                )

            raise ValueError(f"Unexpected impact action: {impact_action}")

        except Exception as e:
            print(f"Error getting economic impact: {str(e)}")
            raise e

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
        option_pairs = "&".join([f"{k}={v}" for k, v in options.items()])
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

    def _extract_dataset_version(self, dataset: str) -> str | None:
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
                if bundle.get(key) is None and value is not None:
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

    # Dataset keywords that are passed directly to the simulation API
    # instead of being resolved via get_default_dataset
    PASSTHROUGH_DATASETS = {
        "national-with-breakdowns",
        "national-with-breakdowns-test",
    }

    def _setup_data(
        self, country_id: str, region: str, dataset: str = "default"
    ) -> str:
        """
        Determine the dataset to use based on the country and region.

        If the dataset is in PASSTHROUGH_DATASETS, it will be passed directly
        to the simulation API. If the dataset matches a configured dataset alias
        for the country, resolve it to the published dataset URI. Otherwise,
        uses policyengine's get_default_dataset to resolve the appropriate GCS
        path.
        """
        # If the dataset is a recognized passthrough keyword, use it directly
        if dataset in self.PASSTHROUGH_DATASETS:
            return dataset

        if "://" in dataset:
            return dataset

        # Resolve explicit dataset aliases exposed in metadata.
        country_datasets = configured_datasets.get(country_id, {})
        if dataset in country_datasets:
            return country_datasets[dataset]

        try:
            return get_default_dataset(country_id, region)
        except ValueError as e:
            logger.log_struct(
                {
                    "message": f"Error getting default dataset for country={country_id}, region={region}: {str(e)}",
                },
                severity="ERROR",
            )
            raise

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
