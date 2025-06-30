from typing import Annotated
import json
import traceback
import datetime
import time
import os
from typing import Any, Literal
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from google.cloud import workflows_v1
from google.cloud.workflows import executions_v1
from policyengine_api.gcp_logging import logger
from policyengine_api.jobs import BaseJob
from policyengine_api.services.reform_impacts_service import (
    ReformImpactsService,
)
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.utils.hugging_face import get_latest_commit_tag

load_dotenv()

reform_impacts_service = ReformImpactsService()

ENHANCED_FRS = "hf://policyengine/policyengine-uk-data/enhanced_frs_2022_23.h5"
FRS = "hf://policyengine/policyengine-uk-data/frs_2022_23.h5"

ENHANCED_CPS = "hf://policyengine/policyengine-us-data/enhanced_cps_2024.h5"
CPS = "hf://policyengine/policyengine-us-data/cps_2023.h5"
POOLED_CPS = "hf://policyengine/policyengine-us-data/pooled_3_year_cps_2023.h5"

datasets = {
    "uk": {
        "enhanced_frs": ENHANCED_FRS,
        "frs": FRS,
    },
    "us": {
        "enhanced_cps": ENHANCED_CPS,
        "cps": CPS,
        "pooled_cps": POOLED_CPS,
    },
}

us_dataset_version = get_latest_commit_tag(
    repo_id="policyengine/policyengine-us-data",
    repo_type="model",
)
uk_dataset_version = get_latest_commit_tag(
    repo_id="policyengine/policyengine-uk-data-private",
    repo_type="model",
)

for dataset in datasets["uk"]:
    datasets["uk"][dataset] = f"{datasets['uk'][dataset]}@{uk_dataset_version}"

for dataset in datasets["us"]:
    datasets["us"][dataset] = f"{datasets['us'][dataset]}@{us_dataset_version}"


class CalculateEconomySimulationJob(BaseJob):
    def __init__(self):
        super().__init__()
        if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") is None:
            logger.log_text(
                "GOOGLE_APPLICATION_CREDENTIALS not set; unable to run simulation API.",
                severity="ERROR",
            )
            raise ValueError(
                "GOOGLE_APPLICATION_CREDENTIALS not set; unable to run simulation API."
            )
        self.sim_api = SimulationAPI()

    def run(
        self,
        baseline_policy_id: int,
        policy_id: int,
        country_id: str,
        region: str,
        dataset: str,
        time_period: str,
        options: dict,
        baseline_policy: dict,
        reform_policy: Annotated[str, "String-formatted JSON"],
        target: Literal["general", "cliff"] = "general",
    ):
        job_id = self._set_job_id()
        job_setup_options = {
            "job_id": job_id,
            "job_type": "CALCULATE_ECONOMY_SIMULATION_JOB",
            "baseline_policy_id": baseline_policy_id,
            "reform_policy_id": policy_id,
            "country_id": country_id,
            "region": region,
            "dataset": dataset,
            "time_period": time_period,
            "options": options,
            "baseline_policy": baseline_policy,
            "reform_policy": reform_policy,
            "workflow_id": None,
            "model_version": COUNTRY_PACKAGE_VERSIONS[country_id],
            "include_cliffs": target == "cliff",
            "data_version": (
                uk_dataset_version
                if country_id == "uk"
                else us_dataset_version
            ),
        }
        logger.log_struct(
            {
                "message": f"Starting job with job_id {job_id}",
                **job_setup_options,
            },
            severity="INFO",
        )

        options_hash = None
        try:
            # Configure inputs
            # Note for anyone modifying options_hash: redis-queue treats ":" as a namespace
            # delimiter; don't use colons in options_hash
            options_hash = (
                "[" + "&".join([f"{k}={v}" for k, v in options.items()]) + "]"
            )
            baseline_policy_id = int(baseline_policy_id)
            policy_id = int(policy_id)

            logger.log_struct(
                {
                    "message": "Checking if completed result already exists",
                    **job_setup_options,
                }
            )

            # Check if a completed result already exists
            existing = reform_impacts_service.get_all_reform_impacts(
                country_id,
                policy_id,
                baseline_policy_id,
                region,
                dataset,
                time_period,
                options_hash,
                COUNTRY_PACKAGE_VERSIONS[country_id],
            )
            if any(x["status"] == "ok" for x in existing):
                logger.log_struct(
                    {
                        "message": "Found existing completed result",
                        **job_setup_options,
                    }
                )
                return

            logger.log_struct(
                {
                    "message": "No existing completed result found, proceeding with computation",
                    **job_setup_options,
                }
            )
            # Query existing impacts before deleting
            existing = reform_impacts_service.get_all_reform_impacts(
                country_id,
                policy_id,
                baseline_policy_id,
                region,
                dataset,
                time_period,
                options_hash,
                COUNTRY_PACKAGE_VERSIONS[country_id],
            )

            # Delete any existing reform impact rows with the same identifiers
            reform_impacts_service.delete_reform_impact(
                country_id,
                policy_id,
                baseline_policy_id,
                region,
                dataset,
                time_period,
                options_hash,
            )

            logger.log_struct(
                {
                    "message": "Creating new reform impact computation process",
                    **job_setup_options,
                }
            )
            # Insert new reform impact row with status 'computing'
            reform_impacts_service.set_reform_impact(
                country_id=country_id,
                policy_id=policy_id,
                baseline_policy_id=baseline_policy_id,
                region=region,
                dataset=dataset,
                time_period=time_period,
                options=json.dumps(options),
                options_hash=options_hash,
                status="computing",
                api_version=COUNTRY_PACKAGE_VERSIONS[country_id],
                reform_impact_json=json.dumps({}),
                start_time=datetime.datetime.strftime(
                    datetime.datetime.now(datetime.timezone.utc),
                    "%Y-%m-%d %H:%M:%S.%f",
                ),
            )

            # Set up sim API job
            logger.log_struct(
                {
                    "message": "Setting up sim API job",
                    **job_setup_options,
                }
            )
            sim_config: dict[str, Any] = self.sim_api._setup_sim_options(
                country_id=country_id,
                scope="macro",
                reform_policy=reform_policy,
                baseline_policy=baseline_policy,
                time_period=time_period,
                region=region,
                dataset=dataset,
                model_version=COUNTRY_PACKAGE_VERSIONS[country_id],
                include_cliffs=target == "cliff",
                data_version=(
                    uk_dataset_version
                    if country_id == "uk"
                    else us_dataset_version
                ),
            )

            sim_api_execution = self.sim_api.run(sim_config)
            execution_id = self.sim_api.get_execution_id(sim_api_execution)

            job_setup_options["workflow_id"] = execution_id

            progress_log = {
                **job_setup_options,
                "message": "Sim API job started",
            }
            logger.log_struct(progress_log, severity="INFO")

            # Wait for job to complete
            sim_api_output = None
            try:
                sim_api_output = self.sim_api.wait_for_completion(
                    sim_api_execution
                )

            except Exception as e:
                trace = traceback.format_exc()
                # If job fails, send error log to GCP
                error_log = {
                    **job_setup_options,
                    "message": "Sim API job failed",
                    "error": str(e),
                    "traceback": trace,
                }
                logger.log_struct(error_log, severity="ERROR")

            # Finally, update all reform impact rows with the same baseline and reform policy IDs
            reform_impacts_service.set_complete_reform_impact(
                country_id=country_id,
                reform_policy_id=policy_id,
                baseline_policy_id=baseline_policy_id,
                region=region,
                dataset=dataset,
                time_period=time_period,
                options_hash=options_hash,
                reform_impact_json=json.dumps(sim_api_output),
            )

        except Exception as e:
            reform_impacts_service.set_error_reform_impact(
                country_id,
                policy_id,
                baseline_policy_id,
                region,
                dataset,
                time_period,
                options_hash,
                message=traceback.format_exc(),
            )
            logger.log_struct(
                {
                    "message": "Error during job execution",
                    "error": str(e),
                    **job_setup_options,
                }
            )
            raise e

    def _set_job_id(self) -> str:
        """
        Generate a unique job ID based on the current timestamp and a random number.
        This is used to track the job in the database and logs.
        """
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        random_number = np.random.randint(1000, 9999)
        return f"job_{timestamp}_{random_number}"


class SimulationAPI:
    project: str
    location: str
    workflow: str

    def __init__(self):
        self.project = "prod-api-v2-c4d5"
        self.location = "us-central1"
        self.workflow = "simulation-workflow"

    def run(self, payload: dict) -> executions_v1.Execution:
        """
        Run a simulation using the v2 API

        Parameters:
        -----------
        payload : dict
            The payload to send to the API

        Returns:
        --------
        execution : executions_v1.Execution
            The execution object
        """
        self.execution_client = executions_v1.ExecutionsClient()
        self.workflows_client = workflows_v1.WorkflowsClient()
        json_input = json.dumps(payload)
        workflow_path = self.workflows_client.workflow_path(
            self.project, self.location, self.workflow
        )
        execution = self.execution_client.create_execution(
            parent=workflow_path,
            execution=executions_v1.Execution(argument=json_input),
        )
        return execution

    def get_execution_id(self, execution: executions_v1.Execution) -> str:
        return execution.name

    def get_execution_status(self, execution: executions_v1.Execution) -> str:
        """
        Get the status of an execution

        Parameters:
        -----------
        execution : executions_v1.Execution
            The execution object

        Returns:
        --------
        status : str
            The status of the execution
        """
        return self.execution_client.get_execution(
            name=execution.name
        ).state.name

    def get_execution_result(
        self, execution: executions_v1.Execution
    ) -> dict | None:
        """
        Get the result of an execution

        Parameters:
        -----------
        execution : executions_v1.Execution
            The execution object

        Returns:
        --------
        result : str
            The result of the execution
        """
        result = self.execution_client.get_execution(
            name=execution.name
        ).result
        try:
            return json.loads(result)
        except:
            return None
        return result

    def wait_for_completion(
        self, execution: executions_v1.Execution
    ) -> dict | None:
        """
        Wait for an execution to complete

        Parameters:
        -----------
        execution : executions_v1.Execution
            The execution object

        Returns:
        --------
        result : str
            The result of the execution
        """
        while self.get_execution_status(execution) == "ACTIVE":
            time.sleep(5)
            print("Waiting for sim API job to complete...")

        return self.get_execution_result(execution)

    def _setup_sim_options(
        self,
        country_id: str,
        reform_policy: Annotated[str, "String-formatted JSON"],
        baseline_policy: Annotated[str, "String-formatted JSON"],
        region: str,
        dataset: str | None,
        time_period: str,
        scope: Literal["macro", "household"] = "macro",
        include_cliffs: bool = False,
        model_version: str | None = None,
        data_version: str | None = None,
    ) -> dict[str, Any]:
        """
        Set up the simulation options for the simulation API job.
        """

        return {
            "country": country_id,
            "scope": scope,
            "reform": json.loads(reform_policy),
            "baseline": json.loads(baseline_policy),
            "time_period": time_period,
            "include_cliffs": include_cliffs,
            "region": self._setup_region(country_id=country_id, region=region),
            "data": self._setup_data(
                dataset=dataset, country_id=country_id, region=region
            ),
            "model_version": model_version,
            "data_version": data_version,
        }

    def _setup_region(self, country_id: str, region: str) -> str:
        """
        Convert API v1 'region' option to API v2-compatible 'region' option.
        """

        # For US, states must be prefixed with 'state/'
        if country_id == "us" and region != "us":
            return "state/" + region

        return region

    def _setup_data(
        self, dataset: str | None, country_id: str, region: str
    ) -> str | None:
        """
        Take API v1 'data' string literals, which reference a dataset name,
        and convert to relevant GCP filepath. In future, this should be
        redone to use a more robust method of accessing datasets.
        """

        # Enhanced CPS runs must reference ECPS dataset in Google Cloud bucket
        if dataset == "enhanced_cps":
            return "gs://policyengine-us-data/enhanced_cps_2024.h5"

        # US state-level simulations must reference pooled CPS dataset
        if country_id == "us" and region != "us":
            return "gs://policyengine-us-data/pooled_3_year_cps_2023.h5"

        # All others receive no sim API 'data' arg
        return None
