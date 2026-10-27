"""Status, request and result types of the economy service, and its limits."""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from policyengine_api.gcp_logging import logger
from policyengine_api.libs.simulation_entrypoint import SimulationRunProgress
from policyengine_api.services.economic_impact_request import LocalAreaBreakdown
from policyengine_api.spm import SPMSelection
from policyengine_api.utils import budget_window as budget_window_utils


class ImpactAction(Enum):
    """What to do with an economic impact request, given its stored calculation."""

    COMPLETED = "completed"
    FAILED = "failed"
    COMPUTING = "computing"
    CREATE = "create"


class ImpactStatus(Enum):
    """Enum for the status of an economic impact calculation."""

    COMPUTING = "computing"
    OK = "ok"
    ERROR = "error"


COMPLETE_STATUSES = [ImpactStatus.OK.value, ImpactStatus.ERROR.value]
COMPUTING_STATUS = ImpactStatus.COMPUTING.value
BUDGET_WINDOW_MAX_ACTIVE_YEARS = budget_window_utils.BUDGET_WINDOW_MAX_ACTIVE_YEARS
BUDGET_WINDOW_MAX_YEARS = budget_window_utils.BUDGET_WINDOW_MAX_YEARS
BUDGET_WINDOW_MAX_END_YEAR = budget_window_utils.BUDGET_WINDOW_MAX_END_YEAR
BUDGET_WINDOW_SUBMISSION_VALIDATION_ERROR_STATUS_CODES = {400, 422}
# Statuses with which the simulation API refuses a breakdown it cannot run:
# 400 from a gateway whose routed .py release does not declare breakdowns, and
# 422 from an entry deployment that does not know the field.
LOCAL_AREA_BREAKDOWN_REFUSAL_STATUS_CODES = frozenset({400, 422})
# How long a failed breakdown's error is returned before the next request may
# submit a new job. Short, so the app's Retry works soon, but long enough that
# a client retrying on every 502 does not start a run on the large local-area
# dataset each time.
LOCAL_AREA_BREAKDOWN_FAILURE_SECONDS = 120
LOCAL_AREA_BREAKDOWN_RETRY_NOTE = (
    "A new local-area breakdown can be requested "
    f"{LOCAL_AREA_BREAKDOWN_FAILURE_SECONDS // 60} minutes after this failure."
)
# The telemetry simulation_kind of a breakdown run. The simulation API's
# telemetry envelope forbids extra fields, so the run is marked here rather
# than by a new field; geography_type and geography_code still name its region.
LOCAL_AREA_BREAKDOWN_SIMULATION_KIND = "local_area_breakdown"
BUDGET_WINDOW_CLAIM_ATTEMPTS = 3
REFORM_IMPACT_START_CLAIM_ATTEMPTS = 3
# A budget-window progress message names this many computing years and counts
# the rest.
BUDGET_WINDOW_LISTED_COMPUTING_YEARS = 2


@dataclass(frozen=True)
class BudgetWindowYearProgress:
    """Which years of a budget window are completed, computing and still queued."""

    completed_years: list[str]
    computing_years: list[str]
    queued_years: list[str]


@dataclass(frozen=True)
class RuntimeBundleIdentity:
    """The dataset and package versions that an options hash identifies.

    ``runtime_app_name`` names the resolved simulation worker once it is known.
    """

    dataset: str
    model_version: str | None
    policyengine_version: str | None = None
    data_version: str | None = None
    runtime_app_name: str | None = None


class SimulationOptions(BaseModel):
    """The job payload sent to the Simulation entrypoint for one economy simulation."""

    spm: SPMSelection | None = None
    country: str
    scope: Literal["macro", "household"] = "macro"
    reform: dict[str, Any]
    baseline: dict[str, Any]
    time_period: str | int
    include_cliffs: bool = False
    region: str
    model_version: str | None = None
    policyengine_version: str | None = None
    # Left out of the payload unless set, so national submissions are unchanged.
    breakdown: LocalAreaBreakdown | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class EconomicImpactSetupOptions(BaseModel):
    """One resolved economic impact request.

    It holds the request's cache identity, the runtime bundle versions and the
    submission claim token that guards against duplicate simulation jobs.
    """

    submission_claim_id: str
    observability_id: str | None = None
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
    """The status of an economic impact calculation and, once complete, its result.

    ``data`` holds the reform impact JSON when the status is ok, and ``message``
    explains an error.
    """

    status: ImpactStatus
    data: dict | None = None
    message: str | None = None
    # Stage fields relayed from the Simulation Entrypoint while computing.
    # Kept out of to_dict(); the route adds them only when present.
    run_progress: SimulationRunProgress | None = None

    model_config = {"frozen": True}  # Make model immutable

    def to_dict(self) -> dict[str, str | dict | None]:
        """Convert the EconomicImpactResult to a dictionary."""
        return {
            "status": self.status.value,
            "data": self.data,
            "message": self.message,
        }

    @classmethod
    def completed(cls, data: dict) -> "EconomicImpactResult":
        """Create an EconomicImpactResult for a completed impact calculation."""
        return cls(status=ImpactStatus.OK, data=data)

    @classmethod
    def computing(
        cls, run_progress: SimulationRunProgress | None = None
    ) -> "EconomicImpactResult":
        """Create an EconomicImpactResult for a computing impact calculation."""
        return cls(status=ImpactStatus.COMPUTING, data=None, run_progress=run_progress)

    @classmethod
    def error(cls, message: str) -> "EconomicImpactResult":
        """Create an EconomicImpactResult for an error in the impact calculation."""
        logger.log_struct({"message": message}, severity="ERROR")
        return cls(status=ImpactStatus.ERROR, data=None, message=message)


class BudgetWindowEconomicImpactResult(BaseModel):
    """Model for a batch budget-window economic impact response."""

    status: ImpactStatus
    data: dict | None = None
    progress: int | None = None
    completed_years: list[str] = Field(default_factory=list)
    computing_years: list[str] = Field(default_factory=list)
    queued_years: list[str] = Field(default_factory=list)
    message: str | None = None
    error: str | None = None
    cache_status: str | None = None

    model_config = {"frozen": True}

    def to_dict(self) -> dict[str, Any]:
        """Return the response body; ``cache_status`` is internal and is left out."""
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
        cls, data: dict, *, cache_status: str | None = None
    ) -> "BudgetWindowEconomicImpactResult":
        """Build a finished result with progress at 100."""
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
        years: BudgetWindowYearProgress,
        message: str,
        cache_status: str | None = None,
    ) -> "BudgetWindowEconomicImpactResult":
        """Build an in-progress result listing the done, running and queued years."""
        return cls(
            status=ImpactStatus.COMPUTING,
            data=None,
            progress=progress,
            completed_years=years.completed_years,
            computing_years=years.computing_years,
            queued_years=years.queued_years,
            message=message,
            cache_status=cache_status,
        )

    @classmethod
    def failed(
        cls,
        message: str,
        *,
        completed_years: list[str] | None = None,
        computing_years: list[str] | None = None,
        queued_years: list[str] | None = None,
        cache_status: str | None = None,
    ) -> "BudgetWindowEconomicImpactResult":
        """Build an error result, copying the message into ``error`` and logging it."""
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
