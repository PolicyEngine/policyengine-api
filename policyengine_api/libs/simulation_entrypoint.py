"""HTTP client for the configured PolicyEngine Simulation Entrypoint."""

import os
import sys
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx
from policyengine_observability import instrument_httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from policyengine_api.gcp_logging import logger
from policyengine_api.libs.gateway_auth import (
    GatewayAuthError,
    GatewayAuthTokenProvider,
    GatewayBearerAuth,
    _require_all_or_none_gateway_auth_env,
    gateway_auth_required,
)
from policyengine_api.migration_flags import get_sim_entrypoint
from policyengine_api.observability import get_runtime
from policyengine_api.observability.identifiers import OBSERVABILITY_ID_HEADER
from policyengine_api.request_context import (
    REQUEST_ID_HEADER,
    current_observability_id,
    current_request_id,
)
from policyengine_api.worker_spm import raise_worker_spm_error, validate_worker_spm


def _required_base_url(env_name: str) -> str:
    value = os.environ.get(env_name, "").strip()
    if not value:
        msg = f"{env_name} is required"
        raise ValueError(msg)

    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        msg = (
            f"{env_name} must be an absolute HTTP(S) base URL without "
            "credentials, a query, or a fragment"
        )
        raise ValueError(msg)
    return value.rstrip("/")


def resolve_simulation_entrypoint_url(entrypoint: str | None = None) -> str:
    """Resolve old/new upstream URLs without conflating their configuration."""
    selected_entrypoint = entrypoint or get_sim_entrypoint()
    if selected_entrypoint == "old_gateway_direct":
        return _required_base_url("OLD_SIMULATION_GATEWAY_URL")
    if selected_entrypoint == "cloud_run_simulation_entrypoint":
        return _required_base_url("SIMULATION_ENTRYPOINT_URL")
    msg = f"Unsupported simulation entrypoint: {selected_entrypoint!r}"
    raise ValueError(msg)


def _attach_current_request_id(request: httpx.Request) -> None:
    """Attach the active API request ID to an outbound simulation request."""
    request_id = current_request_id()
    if request_id is not None:
        request.headers[REQUEST_ID_HEADER] = request_id
    observability_id = current_observability_id()
    if observability_id is not None:
        request.headers[OBSERVABILITY_ID_HEADER] = observability_id


class SimulationRunSegments(BaseModel):
    """How many of a running job's segments have finished, out of its total."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    completed: int = Field(ge=0)
    total: int = Field(ge=1)


class SimulationRunProgress(BaseModel):
    """Stage fields of a running Simulation Entrypoint job.

    The entrypoint adds these optional fields to ``GET /jobs/{job_id}`` for
    jobs on workers that report stages (policyengine-sim-api#781). The API
    relays them while an economy run is computing. ``stage`` stays a string:
    later entrypoint versions may add stages, and clients must accept them.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    stage: str | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    progress_max: int | None = Field(default=None, ge=0, le=100)
    submitted_at: AwareDatetime | None = None
    started_at: AwareDatetime | None = None
    stage_started_at: AwareDatetime | None = None
    segments: SimulationRunSegments | None = None

    @classmethod
    def from_status(cls, data: dict) -> "SimulationRunProgress | None":
        """Read the stage fields; never fail a poll because of them."""
        try:
            run_progress = cls.model_validate(data)
        except ValidationError:
            return None
        return run_progress if run_progress.to_dict() else None

    def to_dict(self) -> dict:
        """Return the reported fields as JSON values, leaving out unreported ones."""
        return self.model_dump(mode="json", exclude_none=True)


def _worker_bundle_version(
    versions: object,
    country: str,
    version: str | None,
    policyengine_version: str | None,
) -> str:
    """Return the bundle version the worker's ``/versions`` routes resolve.

    The routes for ``policyengine_version``, or else ``country``/``version``,
    name the bundle whose SPM capability applies. Raise KeyError for a missing
    route, TypeError when the document or route map is not an object, and
    ValueError for any other malformed or ambiguous route.
    """
    if not isinstance(versions, dict):
        msg = "Invalid worker versions response"
        raise TypeError(msg)
    route_kind = "policyengine" if policyengine_version else country
    route_version = policyengine_version or version
    routes = versions[route_kind]
    if not isinstance(routes, dict):
        msg = "Invalid worker route map"
        raise TypeError(msg)
    if route_version is None or route_version == "latest":
        route_version = routes["latest"]
    if not isinstance(route_version, str) or not route_version:
        msg = "Invalid worker route version"
        raise ValueError(msg)
    app_name = routes[route_version]
    if not isinstance(app_name, str) or not app_name:
        msg = "Invalid worker application identity"
        raise ValueError(msg)
    # Registry bundles and their capabilities are keyed by wrapper
    # version. Country-version routes identify only the deployed app;
    # resolve its unique bundle instead of treating the app as a key.
    if policyengine_version:
        return route_version
    bundle_routes = versions["policyengine"]
    if not isinstance(bundle_routes, dict) or any(
        not isinstance(bundle, str) or not bundle or not isinstance(app, str) or not app
        for bundle, app in bundle_routes.items()
    ):
        msg = "Invalid worker bundle route map"
        raise ValueError(msg)
    candidates: list[str] = [
        bundle
        for bundle, app in bundle_routes.items()
        if bundle != "latest" and app == app_name
    ]
    if len(candidates) != 1:
        msg = "Worker route has no unambiguous bundle identity"
        raise ValueError(msg)
    return candidates[0]


@dataclass
class ModalSimulationExecution:
    """Represents a Modal simulation job execution."""

    job_id: str
    status: str
    result: dict | None = None
    error: str | None = None
    policyengine_bundle: dict | None = None
    resolved_app_name: str | None = None
    run_progress: SimulationRunProgress | None = None

    @property
    def name(self) -> str:
        """Alias for job_id."""
        return self.job_id


@dataclass
class ModalBudgetWindowBatchExecution:
    """Represents a budget-window batch execution in the Simulation Entrypoint."""

    batch_job_id: str
    status: str
    progress: int | None = None
    completed_years: list[str] = field(default_factory=list)
    running_years: list[str] = field(default_factory=list)
    queued_years: list[str] = field(default_factory=list)
    failed_years: list[str] = field(default_factory=list)
    result: dict | None = None
    error: str | None = None

    @property
    def name(self) -> str:
        """Alias for batch_job_id."""
        return self.batch_job_id


class SimulationEntrypointClient:
    """HTTP client for the configured Simulation Entrypoint.

    This class provides methods for submitting simulation jobs and
    polling for their status/results via HTTP endpoints.
    """

    def __init__(self, entrypoint: str | None = None) -> None:
        """Connect to ``entrypoint`` (default: the configured one) with gateway auth.

        Raise GatewayAuthError if auth is partly configured, or is required here
        but not configured.
        """
        self.entrypoint = entrypoint or get_sim_entrypoint()
        self.base_url = resolve_simulation_entrypoint_url(self.entrypoint)
        self._token_provider = GatewayAuthTokenProvider()
        _require_all_or_none_gateway_auth_env()
        auth = (
            GatewayBearerAuth(self._token_provider)
            if self._token_provider.configured
            else None
        )
        if auth is None:
            if gateway_auth_required():
                msg = (
                    "Gateway auth is required in this runtime: set "
                    "GATEWAY_AUTH_ISSUER, GATEWAY_AUTH_AUDIENCE, "
                    "GATEWAY_AUTH_CLIENT_ID, and "
                    "GATEWAY_AUTH_CLIENT_SECRET."
                )
                raise GatewayAuthError(msg)
            print(
                "SimulationEntrypointClient initialized without gateway auth; "
                "all GATEWAY_AUTH_* env vars are unset and "
                "GATEWAY_AUTH_REQUIRED is not enabled.",
                file=sys.stderr,
                flush=True,
            )
        self.client = httpx.Client(
            timeout=30.0,
            auth=auth,
            event_hooks={"request": [_attach_current_request_id]},
        )
        instrument_httpx(self.client, get_runtime())

    def _normalize_submission_payload(self, payload: dict) -> dict:
        if "data" in payload or "data_version" in payload:
            msg = "Dataset overrides are not supported"
            raise ValueError(msg)

        from policyengine_api.constants import (
            COUNTRY_PACKAGE_VERSIONS,
            POLICYENGINE_VERSION,
        )

        country = payload.get("country", "us")
        bundle_version = payload.get("policyengine_version") or POLICYENGINE_VERSION
        resolved = validate_worker_spm(
            country,
            payload.get("spm"),
            gateway=self,
            policyengine_version=bundle_version,
            model_version=payload.get("model_version")
            or COUNTRY_PACKAGE_VERSIONS.get(country),
        )
        if resolved is not None:
            if bundle_version == "latest":
                from policyengine_api.spm import SPMValidationError

                error_code = "SPM_SETTINGS_INVALID"
                raise SPMValidationError(
                    error_code,
                    "Canonical SPM execution requires an exact PolicyEngine version",
                )
            payload = {
                **payload,
                "spm": resolved,
                "policyengine_version": bundle_version,
            }

        modal_payload = {
            key: value for key, value in payload.items() if value is not None
        }
        if "model_version" in modal_payload:
            modal_payload["version"] = modal_payload.pop("model_version")
        return modal_payload

    def run(self, payload: dict) -> ModalSimulationExecution:
        """Submit a simulation job to the selected Simulation entrypoint.

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
            raise_worker_spm_error(response)
            response.raise_for_status()
            data = response.json()

            logger.log_struct(
                {
                    "message": "Simulation entrypoint job submitted",
                    "job_id": data.get("job_id"),
                    "observability_id": current_observability_id(),
                    "status": data.get("status"),
                },
                severity="INFO",
            )

            return ModalSimulationExecution(
                job_id=data["job_id"],
                status=data["status"],
                policyengine_bundle=data.get("policyengine_bundle"),
                resolved_app_name=data.get("resolved_app_name"),
            )

        except httpx.HTTPStatusError as e:
            logger.log_struct(
                {
                    "message": f"Simulation entrypoint HTTP error: {e.response.status_code}",
                    "observability_id": current_observability_id(),
                    "response_text": e.response.text[:500],
                },
                severity="ERROR",
            )
            raise

        except httpx.RequestError as e:
            logger.log_struct(
                {
                    "message": f"Simulation entrypoint request error: {str(e)}",
                    "observability_id": current_observability_id(),
                },
                severity="ERROR",
            )
            raise

    def run_budget_window_batch(self, payload: dict) -> ModalBudgetWindowBatchExecution:
        """Submit a budget-window batch job to the selected Simulation entrypoint."""
        try:
            modal_payload = self._normalize_submission_payload(payload)

            response = self.client.post(
                f"{self.base_url}/simulate/economy/budget-window",
                json=modal_payload,
            )
            raise_worker_spm_error(response)
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
                    "message": f"Simulation batch API HTTP error: {e.response.status_code}",
                    "response_text": e.response.text[:500],
                },
                severity="ERROR",
            )
            raise

        except httpx.RequestError as e:
            logger.log_struct(
                {
                    "message": f"Simulation batch API request error: {str(e)}",
                    "observability_id": current_observability_id(),
                },
                severity="ERROR",
            )
            raise

    def get_spm_capability(
        self,
        country: str,
        version: str | None = None,
        *,
        policyengine_version: str | None = None,
    ) -> object:
        """Return the worker's published SPM capability for the bundle it would run.

        The bundle is the one the worker's ``/versions`` routes resolve for
        ``policyengine_version`` or else ``country``/``version``; None means that
        bundle publishes no capability. Raise SPMValidationError if the routes
        are unreachable or ambiguous.
        """
        from policyengine_api.spm import SPMValidationError

        try:
            response = self.client.get(f"{self.base_url}/versions")
            response.raise_for_status()
            versions = response.json()
            bundle_version = _worker_bundle_version(
                versions,
                country,
                version,
                policyengine_version,
            )
            capabilities = versions.get("spm_capabilities")
            return (
                capabilities.get(bundle_version)
                if isinstance(capabilities, dict)
                else None
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            error_code = "SPM_CONFIGURATION_UNAVAILABLE"
            raise SPMValidationError(
                error_code,
                "Cannot validate the selected worker's canonical SPM capability",
            ) from exc

    def resolve_app_name(
        self,
        country: str,
        version: str | None = None,
        policyengine_version: str | None = None,
    ) -> tuple[str, str]:
        """Resolve the current gateway app name for a country/model version."""
        if policyengine_version is not None:
            response = self.client.get(f"{self.base_url}/versions/policyengine")
            raise_worker_spm_error(response)
            response.raise_for_status()
            policyengine_version_map = response.json()
            try:
                return policyengine_version_map[policyengine_version], (
                    version or policyengine_version
                )
            except KeyError as exc:
                msg = f"Unknown policyengine version {policyengine_version}"
                raise ValueError(msg) from exc

        response = self.client.get(f"{self.base_url}/versions/{country}")
        response.raise_for_status()
        version_map = response.json()

        resolved_version = version or version_map["latest"]
        try:
            return version_map[resolved_version], resolved_version
        except KeyError as exc:
            msg = f"Unknown version {resolved_version} for country {country}"
            raise ValueError(msg) from exc

    def get_execution_id(self, execution: ModalSimulationExecution) -> str:
        """Get the job ID from an execution.

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
        """Poll the selected Simulation entrypoint for the current status of a job.

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
            raise_worker_spm_error(response)
            if response.status_code not in (200, 202, 500):
                response.raise_for_status()
            data = response.json()

            return ModalSimulationExecution(
                job_id=job_id,
                status=data["status"],
                result=data.get("result"),
                error=data.get("error"),
                policyengine_bundle=data.get("policyengine_bundle"),
                resolved_app_name=data.get("resolved_app_name"),
                run_progress=SimulationRunProgress.from_status(data),
            )

        except httpx.HTTPStatusError as e:
            logger.log_struct(
                {
                    "message": f"Simulation entrypoint HTTP error polling job {job_id}: {e.response.status_code}",
                    "response_text": e.response.text[:500],
                },
                severity="ERROR",
            )
            raise

        except httpx.RequestError as e:
            logger.log_struct(
                {
                    "message": f"Simulation entrypoint request error polling job {job_id}: {str(e)}",
                },
                severity="ERROR",
            )
            raise

    def get_budget_window_batch_by_id(
        self, batch_job_id: str
    ) -> ModalBudgetWindowBatchExecution:
        """Poll the selected Simulation entrypoint for a budget-window batch."""
        try:
            response = self.client.get(
                f"{self.base_url}/budget-window-jobs/{batch_job_id}"
            )
            raise_worker_spm_error(response)
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
                    "message": f"Simulation batch API HTTP error polling job {batch_job_id}: {e.response.status_code}",
                    "response_text": e.response.text[:500],
                },
                severity="ERROR",
            )
            raise

        except httpx.RequestError as e:
            logger.log_struct(
                {
                    "message": f"Simulation batch API request error polling job {batch_job_id}: {str(e)}",
                },
                severity="ERROR",
            )
            raise

    def get_execution_status(self, execution: ModalSimulationExecution) -> str:
        """Get the status string from an execution.

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

    def get_execution_result(self, execution: ModalSimulationExecution) -> dict | None:
        """Get the result from a completed execution.

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
        """Check if the selected Simulation entrypoint is healthy.

        Returns
        -------
        bool
            True if the API is healthy, False otherwise.

        """
        try:
            response = self.client.get(f"{self.base_url}/health")
        except httpx.HTTPError:
            return False
        else:
            return response.status_code == 200


# Compatibility aliases preserve existing imports and generated-client consumers.
SimulationAPIClient = SimulationEntrypointClient
SimulationAPIModal = SimulationEntrypointClient
resolve_simulation_api_url = resolve_simulation_entrypoint_url

# All compatibility names intentionally reference one client so a process cannot
# split traffic accidentally.
simulation_entrypoint = SimulationEntrypointClient()
simulation_api = simulation_entrypoint
simulation_api_modal = simulation_entrypoint
