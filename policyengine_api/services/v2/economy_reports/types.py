"""Framework-independent data exchanged by the v2 economy report layers.

The Simulation Entrypoint owns economy reports: their simulations, runs and
results live in its database, and only its routes create or read them.
``EconomyReportSimulation`` is those routes as these layers use them.
``policyengine_api.libs.simulation_economy_reports`` implements it with the
generated simulation client, and tests replace it with a fake.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from policyengine_api.query_parameters import ResourceId

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

# The bounds and form the Simulation Entrypoint accepts.
ReportYear = Annotated[int, Field(ge=1900, le=2200, description="The report's year")]
CatalogKey = Annotated[str, Field(min_length=1, max_length=255, pattern=r"^\S+$")]
JSONObject = dict[str, JsonValue]


class ReportStatus(StrEnum):
    """Where a report or report run stands; a report's is its newest run's.

    A report with no run, such as one migrated from v1, is ``not_run``.
    """

    NOT_RUN = "not_run"
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RunTrigger(StrEnum):
    """Why a report runs again: a user's re-run, or one API v1 starts itself."""

    MANUAL = "manual"
    SYSTEM = "system"


class StrictEconomyReportInput(BaseModel):
    """Reject fields outside the reviewed economy report contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SimulationChoice(StrictEconomyReportInput):
    """A simulation's v2 policy and dynamic; neither means current law."""

    policy_id: ResourceId | None = None
    dynamic_id: ResourceId | None = None


class EconomyReportFields(StrictEconomyReportInput):
    """What an economy report compares, apart from its country.

    ``region_code`` is a region of the country's current catalog version
    (``state/ca``, ``country/wales``), and ``dataset_name`` one of its
    datasets; without it the region's default dataset is used.
    """

    kind: Literal["economy"]
    year: ReportYear
    region_code: CatalogKey
    dataset_name: CatalogKey | None = None
    baseline: SimulationChoice
    reform: SimulationChoice


class EconomyReportRunFields(StrictEconomyReportInput):
    """A re-run; ``force`` calculates both simulations again instead of reusing runs."""

    force: bool = False


@dataclass(frozen=True)
class EconomyReportSubmission:
    """A new economy report as the Simulation Entrypoint is asked to create it.

    ``policyengine_version`` selects the country's catalog version.
    """

    country_id: str
    policyengine_version: str
    year: int
    region_code: str
    dataset_name: str | None
    baseline: SimulationChoice
    reform: SimulationChoice


@dataclass(frozen=True)
class RunError:
    """Why a run failed, without user data."""

    code: str
    message: str | None


@dataclass(frozen=True)
class SimulationRecord:
    """A simulation: one policy and dynamic applied to one region."""

    id: UUID
    kind: str
    country_id: str
    policy_id: UUID | None
    dynamic_id: UUID | None
    region_code: str | None
    dataset_name: str | None
    legacy_simulation_id: int | None
    created_at: datetime


@dataclass(frozen=True)
class SimulationRunRecord:
    """One execution of a simulation for a catalog version and year."""

    id: UUID
    simulation_id: UUID
    status: str
    attempt: int
    trigger: str
    error: RunError | None
    dispatched_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class ComparisonRecord:
    """A report run's comparison step, which computes the report's result."""

    status: str
    error: RunError | None
    dispatched_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True)
class EconomyReportRunRecord:
    """One calculation of a report: two simulation runs and their comparison.

    ``tax_benefit_model_version_id`` is the catalog version it ran on, and
    ``policyengine_version`` that version's PolicyEngine.py version. ``stage``
    says what a running run is doing.
    """

    id: UUID
    report_id: UUID
    trigger: str
    tax_benefit_model_version_id: UUID
    policyengine_version: str | None
    year: int
    status: ReportStatus
    stage: str | None
    error: RunError | None
    baseline_run: SimulationRunRecord
    reform_run: SimulationRunRecord
    comparison: ComparisonRecord
    created_at: datetime


@dataclass(frozen=True)
class EconomyReportRecord:
    """An economy report, its newest run and, once that run succeeded, its result.

    ``result`` is today's economy result format (``SingleYearMacroOutput``).
    """

    id: UUID
    country_id: str
    year: int
    options: JSONObject
    legacy_report_id: int | None
    created_at: datetime
    baseline_simulation: SimulationRecord
    reform_simulation: SimulationRecord
    status: ReportStatus
    run: EconomyReportRunRecord | None
    result: JSONObject | None


class SimulationRecordNotFoundError(LookupError):
    """The Simulation Entrypoint has no such report or simulation."""


class SimulationRequestRefusedError(ValueError):
    """The Simulation Entrypoint cannot run the request; the message says why.

    For example: no catalog for the PolicyEngine.py version, no such region or
    dataset, or a policy or dynamic that does not exist for the country.
    """


class SimulationServiceUnavailableError(RuntimeError):
    """The Simulation Entrypoint cannot be used now.

    It is not configured or reachable here, it refused API v1's credentials,
    it answered that its own database or Modal environment is unavailable, or
    it answered in a form API v1 does not understand.
    """


class EconomyReportSimulation(Protocol):
    """The Simulation Entrypoint's economy report routes.

    Every method raises ``SimulationServiceUnavailableError`` when the
    entrypoint cannot be used.
    """

    def submit_report(self, submission: EconomyReportSubmission) -> EconomyReportRecord:
        """Create the report's simulations, the report and its first run, and start it.

        Raise ``SimulationRequestRefusedError`` when it cannot run.
        """
        ...

    def get_report(self, report_id: UUID) -> EconomyReportRecord:
        """Return a report; raise ``SimulationRecordNotFoundError`` if unknown."""
        ...

    def get_report_by_legacy_id(self, legacy_report_id: int) -> EconomyReportRecord:
        """Return the report migrated from a v1 report output number.

        Raise ``SimulationRecordNotFoundError`` when none was.
        """
        ...

    def run_report(
        self,
        report_id: UUID,
        *,
        policyengine_version: str,
        trigger: RunTrigger,
        force: bool,
    ) -> EconomyReportRunRecord:
        """Run a report again on the catalog version of ``policyengine_version``.

        Existing simulation runs are reused unless ``force`` is set. Raise
        ``SimulationRecordNotFoundError`` for an unknown report and
        ``SimulationRequestRefusedError`` when it cannot run.
        """
        ...

    def list_report_runs(self, report_id: UUID) -> tuple[EconomyReportRunRecord, ...]:
        """Return a report's runs, newest first.

        Raise ``SimulationRecordNotFoundError`` for an unknown report.
        """
        ...

    def get_simulation(self, simulation_id: UUID) -> SimulationRecord:
        """Return a simulation; raise ``SimulationRecordNotFoundError`` if unknown."""
        ...
