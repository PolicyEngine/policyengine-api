"""
HTTP client for the Modal Simulation API.

This module provides a client for submitting simulation jobs to the
Modal-based simulation API and polling for results.
"""

import os
import sys
from dataclasses import dataclass, field
from typing import Optional

import httpx
from policyengine_api.gcp_logging import logger
from policyengine_api.libs.gateway_auth import (
    GatewayAuthError,
    GatewayAuthTokenProvider,
    GatewayBearerAuth,
    _require_all_or_none_gateway_auth_env,
    gateway_auth_required,
)


@dataclass
class ModalSimulationExecution:
    """
    Represents a Modal simulation job execution.
    """

    job_id: str
    status: str
    run_id: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    policyengine_bundle: Optional[dict] = None
    resolved_app_name: Optional[str] = None

    @property
    def name(self) -> str:
        """Alias for job_id."""
        return self.job_id


@dataclass
class ModalBudgetWindowBatchExecution:
    """
    Represents a budget-window batch execution in the Modal simulation API.
    """

    batch_job_id: str
    status: str
    progress: Optional[int] = None
    completed_years: list[str] = field(default_factory=list)
    running_years: list[str] = field(default_factory=list)
    queued_years: list[str] = field(default_factory=list)
    failed_years: list[str] = field(default_factory=list)
    result: Optional[dict] = None
    error: Optional[str] = None

    @property
    def name(self) -> str:
        """Alias for batch_job_id."""
        return self.batch_job_id


class SimulationAPIModal:
    """
    HTTP client for the Modal Simulation API.

    This class provides methods for submitting simulation jobs and
    polling for their status/results via HTTP endpoints.
    """

    def __init__(self):
        self.base_url = os.environ.get(
            "SIMULATION_API_URL",
            "https://policyengine--policyengine-simulation-gateway-web-app.modal.run",
        )
        self._token_provider = GatewayAuthTokenProvider()
        _require_all_or_none_gateway_auth_env()
        auth = (
            GatewayBearerAuth(self._token_provider)
            if self._token_provider.configured
            else None
        )
        if auth is None:
            if gateway_auth_required():
                raise GatewayAuthError(
                    "Gateway auth is required in this runtime: set "
                    "GATEWAY_AUTH_ISSUER, GATEWAY_AUTH_AUDIENCE, "
                    "GATEWAY_AUTH_CLIENT_ID, and "
                    "GATEWAY_AUTH_CLIENT_SECRET."
                )
            print(
                "SimulationAPIModal initialized without gateway auth; "
                "all GATEWAY_AUTH_* env vars are unset and "
                "GATEWAY_AUTH_REQUIRED is not enabled.",
                file=sys.stderr,
                flush=True,
            )
        self.client = httpx.Client(timeout=30.0, auth=auth)

    def _normalize_submission_payload(self, payload: dict) -> dict:
        modal_payload = {
            key: value for key, value in payload.items() if value is not None
        }
        if "model_version" in modal_payload:
            modal_payload["version"] = modal_payload.pop("model_version")
        modal_payload.pop("data_version", None)
        return modal_payload

    def run(self, payload: dict) -> ModalSimulationExecution:
        """
        Submit a simulation job to the Modal API.

        Parameters
        ----------
        payload : dict
            The simulation parameters (country, reform, baseline, etc.)
            Expected to match the simulation gateway submission schema.

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
            modal_payload = self._normalize_submission_payload(payload)

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
                    "run_id": data.get("run_id"),
                    "status": data.get("status"),
                },
                severity="INFO",
            )

            return ModalSimulationExecution(
                job_id=data["job_id"],
                status=data["status"],
                policyengine_bundle=data.get("policyengine_bundle"),
                resolved_app_name=data.get("resolved_app_name"),
                run_id=data.get("run_id"),
            )

        except httpx.HTTPStatusError as e:
            logger.log_struct(
                {
                    "message": f"Modal API HTTP error: {e.response.status_code}",
                    "run_id": (payload.get("_telemetry") or {}).get("run_id"),
                    "response_text": e.response.text[:500],
                },
                severity="ERROR",
            )
            raise

        except httpx.RequestError as e:
            logger.log_struct(
                {
                    "message": f"Modal API request error: {str(e)}",
                    "run_id": (payload.get("_telemetry") or {}).get("run_id"),
                },
                severity="ERROR",
            )
            raise

    def run_budget_window_batch(self, payload: dict) -> ModalBudgetWindowBatchExecution:
        """
        Submit a budget-window batch job to the Modal API.
        """
        try:
            modal_payload = self._normalize_submission_payload(payload)

            response = self.client.post(
                f"{self.base_url}/simulate/economy/budget-window",
                json=modal_payload,
            )
            response.raise_for_status()
            data = response.json()

            logger.log_struct(
                {
                    "message": "Modal budget-window batch submitted",
                    "batch_job_id": data.get("batch_job_id"),
                    "status": data.get("status"),
                },
                severity="INFO",
            )

            return ModalBudgetWindowBatchExecution(
                batch_job_id=data["batch_job_id"],
                status=data["status"],
            )

        except httpx.HTTPStatusError as e:
            logger.log_struct(
                {
                    "message": f"Modal batch API HTTP error: {e.response.status_code}",
                    "response_text": e.response.text[:500],
                },
                severity="ERROR",
            )
            raise

        except httpx.RequestError as e:
            logger.log_struct(
                {
                    "message": f"Modal batch API request error: {str(e)}",
                    "run_id": (payload.get("_telemetry") or {}).get("run_id"),
                },
                severity="ERROR",
            )
            raise

    def resolve_app_name(
        self,
        country: str,
        version: Optional[str] = None,
        policyengine_version: Optional[str] = None,
    ) -> tuple[str, str]:
        """Resolve the current gateway app name for a country/model version."""
        if policyengine_version is not None:
            response = self.client.get(f"{self.base_url}/versions/policyengine")
            response.raise_for_status()
            policyengine_version_map = response.json()
            try:
                return policyengine_version_map[policyengine_version], (
                    version or policyengine_version
                )
            except KeyError as exc:
                raise ValueError(
                    f"Unknown policyengine version {policyengine_version}"
                ) from exc

        response = self.client.get(f"{self.base_url}/versions/{country}")
        response.raise_for_status()
        version_map = response.json()

        resolved_version = version or version_map["latest"]
        try:
            return version_map[resolved_version], resolved_version
        except KeyError as exc:
            raise ValueError(
                f"Unknown version {resolved_version} for country {country}"
            ) from exc

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
            if response.status_code not in (200, 202, 500):
                response.raise_for_status()
            data = response.json()

            return ModalSimulationExecution(
                job_id=job_id,
                status=data["status"],
                run_id=data.get("run_id"),
                result=data.get("result"),
                error=data.get("error"),
                policyengine_bundle=data.get("policyengine_bundle"),
                resolved_app_name=data.get("resolved_app_name"),
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

    def get_budget_window_batch_by_id(
        self, batch_job_id: str
    ) -> ModalBudgetWindowBatchExecution:
        """
        Poll the Modal API for the current status of a budget-window batch.
        """
        try:
            response = self.client.get(
                f"{self.base_url}/budget-window-jobs/{batch_job_id}"
            )
            if response.status_code not in (200, 202, 500):
                response.raise_for_status()
            data = response.json()

            return ModalBudgetWindowBatchExecution(
                batch_job_id=batch_job_id,
                status=data["status"],
                progress=data.get("progress"),
                completed_years=data.get("completed_years", []),
                running_years=data.get("running_years", []),
                queued_years=data.get("queued_years", []),
                failed_years=data.get("failed_years", []),
                result=data.get("result"),
                error=data.get("error"),
            )

        except httpx.HTTPStatusError as e:
            logger.log_struct(
                {
                    "message": f"Modal batch API HTTP error polling job {batch_job_id}: {e.response.status_code}",
                    "response_text": e.response.text[:500],
                },
                severity="ERROR",
            )
            raise

        except httpx.RequestError as e:
            logger.log_struct(
                {
                    "message": f"Modal batch API request error polling job {batch_job_id}: {str(e)}",
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
