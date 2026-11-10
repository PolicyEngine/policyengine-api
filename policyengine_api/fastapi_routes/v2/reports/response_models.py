"""Strict HTTP response models for v2 reports."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue

from policyengine_api.fastapi_routes.v2.simulation_resources_support import (
    error_response,
)
from policyengine_api.services.v2.stored_reports.economy_results.types import (
    EconomyResult,
)

if TYPE_CHECKING:
    from policyengine_api.services.v2.stored_reports.types import (
        ReportRead,
        ReportSummaryRead,
    )


class StrictReportAPIModel(BaseModel):
    """Strict response base that converts the service's dataclass reads."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class PackageVersionsItem(StrictReportAPIModel):
    """A country package version and the PolicyEngine.py version beside it."""

    country_package_version: str
    policyengine_version: str


class ReportRunItem(StrictReportAPIModel):
    """One calculation of a report, on one country package and .py version.

    ``status`` is ``pending``, ``running``, ``succeeded`` or ``failed``, and
    ``error_message`` says why a failed run failed. ``trigger`` is
    ``initial`` for the run the report's creation started.
    """

    id: UUID
    status: Literal["pending", "running", "succeeded", "failed"]
    trigger: Literal["initial", "manual", "system"]
    country_package_version: str
    policyengine_version: str
    baseline_simulation_run_id: UUID
    reform_simulation_run_id: UUID | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class ReportSimulationItem(StrictReportAPIModel):
    """A simulation a report compares; a null policy or dynamic is current law."""

    id: UUID
    policy_id: UUID | None
    dynamic_id: UUID | None


class ReportSummaryItem(StrictReportAPIModel):
    """An economy report comparing a baseline and a reform simulation.

    ``status`` is the newest run's, or ``not_run`` for a report with no run.
    ``run`` is the newest run, whatever its status and versions;
    ``current_versions`` are the versions the Public API runs now, so a
    newest run on other versions is out of date. ``options`` are the options
    the report was created with.
    """

    id: UUID
    country_id: str
    kind: Literal["economy"]
    label: str
    description: str | None
    year: int | None
    region_code: str | None
    dataset_name: str | None
    baseline_simulation: ReportSimulationItem | None
    reform_simulation: ReportSimulationItem | None
    options: dict[str, JsonValue]
    created_at: datetime
    status: Literal["not_run", "pending", "running", "succeeded", "failed"]
    run: ReportRunItem | None
    current_versions: PackageVersionsItem

    @classmethod
    def from_summary(cls, read: ReportSummaryRead) -> ReportSummaryItem:
        """Build the summary from the service's read, without a result."""
        return cls.model_validate(read)


class ReportItem(ReportSummaryItem):
    """An economy report with its newest run's result.

    ``result`` is the single-year economy result, in the format the app reads
    today, once the newest run has succeeded, and null otherwise.
    """

    result: EconomyResult | None

    @classmethod
    def from_read(cls, read: ReportRead) -> ReportItem:
        """Build the item from the service's read, with its result."""
        return cls.model_validate(read)


class ReportDetailResult(StrictReportAPIModel):
    """Result holding one report in ``item``."""

    item: ReportItem


class ReportListResult(StrictReportAPIModel):
    """The listed reports in ``items``, in the order named, without results."""

    items: list[ReportSummaryItem]


ResultT = TypeVar("ResultT")


class ReportSuccessResponse(StrictReportAPIModel, Generic[ResultT]):
    """Success envelope: ``status`` "ok", a null ``message`` and the ``result``."""

    status: Literal["ok"] = "ok"
    message: None = None
    result: ResultT


class ReportDetailResponse(ReportSuccessResponse[ReportDetailResult]):
    """Success response holding one report."""


class ReportListResponse(ReportSuccessResponse[ReportListResult]):
    """Success response holding the listed reports."""


# Every report route can answer these.
REPORT_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    422: error_response("The request does not match the schema."),
    500: error_response("The operation could not be completed."),
    503: error_response("The v2 database or the simulation service is unavailable."),
}
READ_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: error_response("No report has this ID in this country."),
    422: error_response(
        "The request does not match the schema, or the report is a household "
        "report or a budget window, which this route does not read yet."
    ),
    500: error_response(
        "The newest run succeeded but its stored result cannot be read, or the "
        "operation could not be completed."
    ),
}
