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

            return

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
        return self.execution_client.get_execution(name=execution.name).state.name

    def get_execution_result(self, execution: executions_v1.Execution) -> dict | None:
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
        result = self.execution_client.get_execution(name=execution.name).result
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
