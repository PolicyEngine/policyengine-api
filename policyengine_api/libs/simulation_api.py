from google.cloud import workflows_v1
from google.cloud.workflows import executions_v1
import os
import json
import time
from typing import Any, Literal, Annotated
from dotenv import load_dotenv
from policyengine_api.gcp_logging import logger
from google.cloud.workflows import executions_v1


load_dotenv()

ExecutionState = executions_v1.types.Execution.State


class SimulationAPI:
    project: str
    location: str
    workflow: str

    def __init__(self):
        if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") is None:
            logger.log_text(
                "GOOGLE_APPLICATION_CREDENTIALS not set; unable to run simulation API.",
                severity="ERROR",
            )
            raise ValueError(
                "GOOGLE_APPLICATION_CREDENTIALS not set; unable to run simulation API."
            )
        self.project = "prod-api-v2-c4d5"
        self.location = "us-central1"
        self.workflow = "simulation-workflow"
        self.execution_client = executions_v1.ExecutionsClient()
        self.workflows_client = workflows_v1.WorkflowsClient()

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

    def get_execution_by_id(self, id: str) -> executions_v1.Execution | None:
        """
        Using an execution ID, fetch the execution from Google Cloud;
        return the execution if present, else None
        """

        return self.execution_client.get_execution(name=id)

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
