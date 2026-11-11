"""Strict HTTP response models for v2 reports."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue

from policyengine_api.fastapi_routes.v2.errors_support import V2ErrorResponse
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


class CreatedReportUnreadableResponse(V2ErrorResponse):
    """The 502 answer when the created report cannot be read back.

    The simulation service created ``report_id``, so the caller reads it
    with ``GET /v2/reports/{report_id}`` rather than submitting it again.
    """

    report_id: UUID


class UnavailableAfterReportCreatedResponse(V2ErrorResponse):
    """The 503 answer when the simulation service failed a new report's run.

    The message gives the service's code and reason. ``report_id`` names the
    report, which ``GET /v2/reports/{report_id}`` reads with its failed run.
    """

    report_id: UUID


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
CREATE_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: error_response("The body and query name different countries."),
    404: error_response("A policy the report names is not stored in the country."),
    413: error_response("The request body exceeds 16 KiB."),
    422: error_response(
        "The request does not match the schema, the country has no economy "
        "reports (such as a household-only country), or the simulation service "
        "cannot run the report: its 422, or its 400 for a region, dataset or "
        "dynamic it does not have. The message says which, with the service's "
        "code and reason."
    ),
    502: {
        "model": V2ErrorResponse | CreatedReportUnreadableResponse,
        "description": (
            "The simulation service created the report, but its answer cannot "
            "be read; it failed (500); its answer was lost after the submission "
            "may have reached it; or a proxy in front of it answered 502 or 504 "
            "in its place. In each case it may have created the report, so "
            "submitting again could create another. Or it created the report, "
            "but the report cannot be read back: the answer gives its "
            "report_id, to read with GET /v2/reports/{report_id} rather than "
            "submitting it again."
        ),
    },
    503: {
        "model": V2ErrorResponse | UnavailableAfterReportCreatedResponse,
        "description": (
            "The simulation service cannot be reached or is not configured; it "
            "answered 503, or a 400 naming no region, dataset or dynamic of the "
            "caller's (such as a catalog version missing while a release "
            "deploys), and the message gives its code and reason; or it "
            "answered in a shape the Public API cannot read. Or the v2 database "
            "is unavailable. When the service created the report before "
            "answering 503, as when Modal refuses the run's call and the "
            "service fails the run, the answer gives its report_id."
        ),
    },
}
