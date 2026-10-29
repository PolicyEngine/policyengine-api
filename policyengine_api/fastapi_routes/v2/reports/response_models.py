"""Strict HTTP response models for v2 economy reports, and both kinds' envelopes.

Household reports' own items are in ``household_response_models``.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from policyengine_api.fastapi_routes.v2.errors import V2ErrorResponse
from policyengine_api.fastapi_routes.v2.reports.household_response_models import (
    HouseholdReportItem,
    HouseholdReportRunItem,
    HouseholdReportSummaryItem,
)
from policyengine_api.services.v2.simulation_entrypoint.types import ReportStatus

if TYPE_CHECKING:
    from policyengine_api.services.v2.simulation_entrypoint.types import (
        EconomyReportRecord,
        EconomyReportRunRecord,
    )


class StrictReportAPIModel(BaseModel):
    """Strict response base that converts the service's dataclass records."""

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        from_attributes=True,
    )


class RunErrorItem(StrictReportAPIModel):
    """Why a run failed, without user data."""

    code: str
    message: str | None


class SimulationItem(StrictReportAPIModel):
    """A simulation: one v2 policy and dynamic applied to one region.

    A null ``policy_id`` and ``dynamic_id`` mean current law. A null
    ``dataset_name`` means the region's default dataset in each catalog
    version.
    """

    id: UUID
    kind: str
    country_id: str
    policy_id: UUID | None
    dynamic_id: UUID | None
    region_code: str | None
    dataset_name: str | None
    legacy_simulation_id: int | None
    created_at: datetime


class SimulationRunItem(StrictReportAPIModel):
    """One execution of a simulation for a catalog version and year.

    ``status`` is ``pending``, ``dispatching``, ``running``, ``succeeded`` or
    ``failed``; ``attempt`` counts forced recalculations.
    """

    id: UUID
    simulation_id: UUID
    status: str
    attempt: int
    trigger: str
    error: RunErrorItem | None
    dispatched_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class ComparisonItem(StrictReportAPIModel):
    """A report run's comparison step, which computes the report's result."""

    status: str
    error: RunErrorItem | None
    dispatched_at: datetime | None
    completed_at: datetime | None


class ReportRunItem(StrictReportAPIModel):
    """One calculation of a report: two simulation runs and their comparison.

    ``trigger`` is ``initial`` for the run a submission starts, ``manual`` for
    a re-run and ``system`` for the run the first read of a report with no run
    starts. ``tax_benefit_model_version_id`` and ``policyengine_version`` name
    the catalog version it ran on. While it runs, ``stage`` is ``queued``,
    ``simulating`` or ``outputs``.
    """

    kind: Literal["economy"] = "economy"
    id: UUID
    report_id: UUID
    trigger: str
    tax_benefit_model_version_id: UUID
    policyengine_version: str | None
    year: int
    status: ReportStatus
    stage: str | None
    error: RunErrorItem | None
    baseline_run: SimulationRunItem
    reform_run: SimulationRunItem
    comparison: ComparisonItem
    created_at: datetime

    @classmethod
    def from_record(cls, record: EconomyReportRunRecord) -> ReportRunItem:
        """Build the response item from the service's report run record."""
        return cls.model_validate(record)


class ReportSummaryItem(StrictReportAPIModel):
    """An economy report comparing a baseline and a reform simulation.

    ``status`` is the newest run's, or ``not_run`` for a report with no run.
    ``legacy_report_id`` is the v1 report output it was migrated from.
    """

    id: UUID
    country_id: str
    kind: Literal["economy"] = "economy"
    year: int
    options: dict[str, JsonValue]
    legacy_report_id: int | None
    created_at: datetime
    baseline_simulation: SimulationItem
    reform_simulation: SimulationItem
    status: ReportStatus
    run: ReportRunItem | None

    @classmethod
    def from_record(cls, record: EconomyReportRecord) -> ReportSummaryItem:
        """Build the summary from the service's report record, without its result."""
        return cls.model_validate(record)


class ReportItem(ReportSummaryItem):
    """An economy report with its result.

    ``result`` holds today's economy result format (``SingleYearMacroOutput``)
    once the newest run has succeeded, and is null otherwise.
    """

    result: dict[str, JsonValue] | None

    @classmethod
    def from_record(cls, record: EconomyReportRecord) -> ReportItem:
        """Build the response item from the service's report record."""
        return cls.model_validate(record)


ReportDetailItem = Annotated[
    ReportItem | HouseholdReportItem, Field(discriminator="kind")
]


class ReportDetailResult(StrictReportAPIModel):
    """Result holding one report, of either kind, in ``item``."""

    item: ReportDetailItem


ReportSummary = Annotated[
    ReportSummaryItem | HouseholdReportSummaryItem, Field(discriminator="kind")
]


class ReportListResult(StrictReportAPIModel):
    """The listed reports of both kinds in ``items``, in the order asked.

    Economy reports are listed without their results and household reports
    without their calculations.
    """

    items: list[ReportSummary]


ReportRunDetailItem = Annotated[
    ReportRunItem | HouseholdReportRunItem, Field(discriminator="kind")
]


class ReportRunDetailResult(StrictReportAPIModel):
    """Result holding one report run, of either kind, in ``item``."""

    item: ReportRunDetailItem


class ReportRunListResult(StrictReportAPIModel):
    """A report's runs in ``items``, newest first."""

    items: list[ReportRunItem]


ResultT = TypeVar("ResultT")


class ReportSuccessResponse(StrictReportAPIModel, Generic[ResultT]):
    """Success envelope: ``status`` "ok", a null ``message`` and the ``result``."""

    status: Literal["ok"] = "ok"
    message: None = None
    result: ResultT


class ReportDetailResponse(ReportSuccessResponse[ReportDetailResult]):
    """Success response holding one report."""


class ReportListResponse(ReportSuccessResponse[ReportListResult]):
    """Success response holding listed reports."""


class ReportRunDetailResponse(ReportSuccessResponse[ReportRunDetailResult]):
    """Success response holding one report run."""


class ReportRunListResponse(ReportSuccessResponse[ReportRunListResult]):
    """Success response holding a report's runs."""


def _error(description: str) -> dict[str, Any]:
    return {"model": V2ErrorResponse, "description": description}


# Every report route can answer these.
REPORT_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    422: _error("The request does not match the schema."),
    500: _error("The operation could not be completed."),
    503: _error("The simulation service or the v2 database is unavailable."),
}
# Submitting or re-running a report can also be refused for the report itself.
REPORT_REFUSAL_RESPONSE: dict[int | str, dict[str, Any]] = {
    422: _error(
        "The request does not match the schema; the country does not have "
        "economy reports (such as a household-only country) or household "
        "calculations; the household has no default year; or the simulation "
        "service cannot run the report (for example, no such region or "
        "dataset in the current catalog version, or a policy changing a "
        "parameter that version lacks); the message says which."
    ),
}
REPORT_NOT_FOUND_RESPONSE: dict[int | str, dict[str, Any]] = {
    404: _error("No report has this ID or v1 number in this country."),
}
RUNS_NOT_FOUND_RESPONSE: dict[int | str, dict[str, Any]] = {
    404: _error(
        "No economy report has this ID in this country. A household report "
        "does not list its runs; its newest run is in the report itself."
    ),
}
REPORT_BODY_RESPONSE: dict[int | str, dict[str, Any]] = {
    413: _error("The request body exceeds 16 KiB."),
}
SUBMIT_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: _error("The body and query name different countries."),
    404: _error(
        "A household report's household or one of its policies does not exist "
        "in this country."
    ),
    **REPORT_BODY_RESPONSE,
    **REPORT_REFUSAL_RESPONSE,
}
READ_RESPONSES: dict[int | str, dict[str, Any]] = {
    **REPORT_NOT_FOUND_RESPONSE,
    502: _error(
        "The simulation service has the report but cannot read back its stored result."
    ),
}
RUN_RESPONSES: dict[int | str, dict[str, Any]] = {
    **REPORT_NOT_FOUND_RESPONSE,
    **REPORT_BODY_RESPONSE,
    **REPORT_REFUSAL_RESPONSE,
}
