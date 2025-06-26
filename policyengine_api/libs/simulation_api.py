from google.cloud import workflows_v1
from google.cloud.workflows import executions_v1
import os
import json
import time
from typing import Any, Literal, Annotated, Optional
from dotenv import load_dotenv
from policyengine_api.gcp_logging import logger
from google.cloud.workflows import executions_v1

# from google.cloud.workflows.executions_v1.types import Execution
from enum import Enum

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

    # def _fetch_all_executions(
    #     self,
    #     view: Literal["BASIC", "FULL"] = "BASIC",
    # ) -> executions_v1.services.executions.pagers.ListExecutionsPager:
    #     """
    #     Fetch all executions for a given workflow.
    #
    #     Args:
    #         view: Whether to fetch basic details (default behavior) or full details about each execution
    #
    #     Returns:
    #         A ListExecutionPager iterable containing all executions for the workflow. This will automatically
    #         fetch new pages as needed.
    #     """

    #     # Construct the parent path for the workflow
    #     parent = self.workflows_client.workflow_path(self.project, self.location, self.workflow)

    #     try:
    #         # Initialize request argument(s)
    #         request = executions_v1.ListExecutionsRequest(
    #             parent=parent,
    #             view=view,
    #         )

    #         # Note that ListExecutionPager automatically requests further pages as needed
    #         page_result: executions_v1.executions.pagers.ListExecutionsPager = self.execution_client.list_executions(request=request)

    #         return page_result

    #     except Exception as e:
    #         logger.log_text(
    #             f"Error fetching all simulation API executions: {e}",
    #             severity="ERROR",
    #         )
    #         raise e
    #
    # def filter_executions_by_config(
    #     self,
    #     target_arguments: dict[str, Any],
    #     execution_states: Optional[list[ExecutionState]] = None,
    # ) -> list[executions_v1.Execution]:
    #     """
    #     Filter executions based on target arguments and execution states.

    #     Args:
    #         target_arguments: Dictionary of arguments to match against
    #         execution_states: List of execution states to filter by
    #                          (e.g., ['ACTIVE', 'SUCCEEDED']). If None, checks all states.

    #     Returns:
    #         A list of matching Execution objects if found, with newest entries first, otherwise an empty list.
    #     """
    #     # Fetch all executions
    #     page_result = self._fetch_all_executions(view="FULL")

    #     target_args_json = json.dumps(target_arguments, sort_keys=True)
    #     print(f"Target arguments JSON: {target_args_json}")
    #     # Iterate through executions
    #     executions: list[executions_v1.Execution] = []
    #     for execution in page_result:
    #         if execution_states and execution.state not in execution_states:
    #             print(f"Skipping execution {execution.name} with state {execution.state}")
    #             continue
    #         print(f"Checking execution: {execution.name}")
    #         with open("executions.txt", "a") as f:
    #             f.write(f"Args from execution: {execution.argument}\n")
    #         try:
    #             # Parse the execution's arguments
    #             execution_args = json.loads(execution.argument)
    #             execution_args_json = json.dumps(execution_args, sort_keys=True)
    #             with open("executions.txt", "a") as f:
    #                 f.write(f"Execution args JSON: {execution_args_json}\n")
    #                 f.write(f"Target args JSON: {target_args_json}\n")

    #             print(f"Comparing execution args with target args...")

    #             # Compare arguments
    #             if execution_args_json == target_args_json:
    #                 with open("executions.txt", "a") as f:
    #                     f.write(f"Match found for execution: {execution.name}\n")

    #                 executions.append(execution)

    #             print(f"No match found for execution: {execution.name}")
    #             with open("executions.txt", "a") as f:
    #                 f.write(f"No match found for execution: {execution.name}\n")

    #         except (json.JSONDecodeError, TypeError):
    #             # Skip executions with invalid JSON arguments
    #             continue
    #
    #     return executions

    # def find_existing_executions(
    #     self,
    #     target_arguments: dict[str, Any],
    #     execution_states: Optional[list[ExecutionState]] = None,
    # ) -> list[executions_v1.Execution]:
    #     """
    #     Check if a workflow execution already exists for the given arguments.

    #     Args:
    #         project_id: Google Cloud project ID
    #         location: Workflow location (e.g., 'us-central1')
    #         workflow_id: Name of the workflow
    #         target_arguments: Dictionary of arguments to match against
    #         execution_states: List of execution states to filter by
    #                          (e.g., ['ACTIVE', 'SUCCEEDED']). If None, checks all states.

    #     Returns:
    #         A list of matching Execution objects if found, with newest entries first, otherwise an empty list.
    #     """
    #     # Construct the parent path for the workflow
    #     parent = self.workflows_client.workflow_path(self.project, self.location, self.workflow)
    #     print(f"Searching for executions in {parent} with arguments: {target_arguments}")

    #     try:
    #         # Create the list request
    #         request = executions_v1.ListExecutionsRequest(parent=parent)
    #         print(f"Request: {request}")

    #         # Add state filter if specified
    #         if execution_states:
    #             # Note: As of recent updates, the Python client supports filtering
    #             # Format: state="STATE_VALUE" or state="STATE1" OR state="STATE2"
    #             state_filters = ' OR '.join([f'state="{state}"' for state in execution_states])
    #             request.filter = state_filters

    #         # List executions (returns newest first by default)
    #         page_result = self.execution_client.list_executions(request=request)

    #         # Convert target arguments to JSON string for comparison
    #         target_args_json = json.dumps(target_arguments, sort_keys=True)
    #         print(f"Target arguments JSON: {target_args_json}")

    #         # Iterate through executions to find a match
    #         executions: list[executions_v1.Execution] = []
    #         print(f"Executions found: {len(page_result)}")
    #         for execution in page_result:
    #             print(f"Checking execution: {execution.name}")
    #             print(dir(execution))
    #             if execution.argument:
    #                 print(f"Execution argument: {execution.argument}")
    #                 try:
    #                     # Parse the execution's arguments
    #                     execution_args = json.loads(execution.argument)
    #                     execution_args_json = json.dumps(execution_args, sort_keys=True)
    #                     print(f"Execution args JSON: {execution_args_json}")

    #                     print(f"Target args JSON: {target_args_json}")

    #                     print(f"Comparing execution args with target args...")

    #                     # Compare arguments
    #                     if execution_args_json == target_args_json:
    #                         print(f"Match found for execution: {execution.name}")
    #                         executions.append(execution)

    #                     print(f"No match found for execution: {execution.name}")

    #                 except (json.JSONDecodeError, TypeError):
    #                     # Skip executions with invalid JSON arguments
    #                     continue
    #             elif not target_arguments:
    #                 # Both execution and target have no arguments
    #                 print(f"Execution {execution.name} has no arguments, adding to results.")
    #                 executions.append(execution)
    #
    #         return executions
    #
    #     except Exception as e:
    #         logger.log_text(
    #             f"Error listing executions for simulation API workflow: {e}",
    #             severity="ERROR",
    #         )
    #         return []

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
