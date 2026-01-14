"""
HTTP client for the Modal Simulation API.

This module provides a client for submitting simulation jobs to the
Modal-based simulation API and polling for results. It implements
the same interface as SimulationAPI (GCP) to allow for easy switching
between backends.
"""

import os
from dataclasses import dataclass
from typing import Optional

import httpx

from policyengine_api.gcp_logging import logger


@dataclass
class ModalSimulationExecution:
    """
    Represents a Modal simulation job execution.

    This class mirrors the interface of GCP's executions_v1.Execution
    to allow the EconomyService to work with either backend.
    """

    job_id: str
    status: str
    result: Optional[dict] = None
    error: Optional[str] = None

    @property
    def name(self) -> str:
        """Alias for job_id to match GCP Execution interface."""
        return self.job_id


class SimulationAPIModal:
    """
    HTTP client for the Modal Simulation API.

    This class provides methods for submitting simulation jobs and
    polling for their status/results via HTTP endpoints, replacing
    the GCP Workflows SDK calls used in SimulationAPI.
    """

    def __init__(self):
        self.base_url = os.environ.get(
            "SIMULATION_API_URL",
            "https://policyengine--policyengine-simulation-gateway-web-app.modal.run",
        )
        self.client = httpx.Client(timeout=30.0)

    def run(self, payload: dict) -> ModalSimulationExecution:
        """
        Submit a simulation job to the Modal API.

        Parameters
        ----------
        payload : dict
            The simulation parameters (country, reform, baseline, etc.)
            Expected to match SimulationOptions schema.

        Returns
        -------
        ModalSimulationExecution
            Execution object with job_id and initial status.

        Raises
        ------
        httpx.HTTPStatusError
            If the API returns an error response.
        """
        try:
            # Map field names from SimulationOptions to Modal API format
            # SimulationOptions uses 'model_version', Modal expects 'version'
            modal_payload = dict(payload)
            if "model_version" in modal_payload:
                modal_payload["version"] = modal_payload.pop("model_version")
            # Remove data_version as Modal doesn't use it
            modal_payload.pop("data_version", None)

            response = self.client.post(
                f"{self.base_url}/simulate/economy/comparison",
                json=modal_payload,
            )
            response.raise_for_status()
            data = response.json()

            logger.log_struct(
                {
                    "message": "Modal simulation job submitted",
                    "job_id": data.get("job_id"),
                    "status": data.get("status"),
                },
                severity="INFO",
            )

            return ModalSimulationExecution(
                job_id=data["job_id"],
                status=data["status"],
            )

        except httpx.HTTPStatusError as e:
            logger.log_struct(
                {
                    "message": f"Modal API HTTP error: {e.response.status_code}",
                    "response_text": e.response.text[:500],
                },
                severity="ERROR",
            )
            raise

        except httpx.RequestError as e:
            logger.log_struct(
                {
                    "message": f"Modal API request error: {str(e)}",
                },
                severity="ERROR",
            )
            raise

    def get_execution_id(self, execution: ModalSimulationExecution) -> str:
        """
        Get the job ID from an execution.

        Parameters
        ----------
        execution : ModalSimulationExecution
            The execution object returned from run().

        Returns
        -------
        str
            The job ID.
        """
        return execution.job_id

    def get_execution_by_id(self, job_id: str) -> ModalSimulationExecution:
        """
        Poll the Modal API for the current status of a job.

        Parameters
        ----------
        job_id : str
            The job ID returned from run().

        Returns
        -------
        ModalSimulationExecution
            Execution object with current status and result if complete.
        """
        try:
            response = self.client.get(f"{self.base_url}/jobs/{job_id}")
            # Note: Modal returns 202 for running, 200 for complete, 500 for failed
            # We handle all cases by checking the status field in the response
            data = response.json()

            return ModalSimulationExecution(
                job_id=job_id,
                status=data["status"],
                result=data.get("result"),
                error=data.get("error"),
            )

        except httpx.HTTPStatusError as e:
            logger.log_struct(
                {
                    "message": f"Modal API HTTP error polling job {job_id}: {e.response.status_code}",
                    "response_text": e.response.text[:500],
                },
                severity="ERROR",
            )
            raise

        except httpx.RequestError as e:
            logger.log_struct(
                {
                    "message": f"Modal API request error polling job {job_id}: {str(e)}",
                },
                severity="ERROR",
            )
            raise

    def get_execution_status(self, execution: ModalSimulationExecution) -> str:
        """
        Get the status string from an execution.

        Parameters
        ----------
        execution : ModalSimulationExecution
            The execution object.

        Returns
        -------
        str
            The status string ("submitted", "running", "complete", "failed").
        """
        return execution.status

    def get_execution_result(
        self, execution: ModalSimulationExecution
    ) -> Optional[dict]:
        """
        Get the result from a completed execution.

        Parameters
        ----------
        execution : ModalSimulationExecution
            The execution object.

        Returns
        -------
        dict or None
            The simulation result if complete, None otherwise.
        """
        return execution.result

    def health_check(self) -> bool:
        """
        Check if the Modal API is healthy.

        Returns
        -------
        bool
            True if the API is healthy, False otherwise.
        """
        try:
            response = self.client.get(f"{self.base_url}/health")
            return response.status_code == 200
        except Exception:
            return False


# Global instance for use throughout the application
simulation_api_modal = SimulationAPIModal()
