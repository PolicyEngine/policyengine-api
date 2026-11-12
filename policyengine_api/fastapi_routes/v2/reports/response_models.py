"""Strict HTTP response models for v2 reports."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from policyengine_api.fastapi_routes.v2.errors_support import (
    V2ErrorResponse,
    V2MissingParametersErrorResponse,
)
from policyengine_api.fastapi_routes.v2.simulation_resources_support import (
    error_response,
)
from policyengine_api.services.v2.stored_reports.budget_window_results.types import (
    BudgetWindowResult,
)
from policyengine_api.services.v2.stored_reports.economy_results.types import (
    EconomyResult,
)

if TYPE_CHECKING:
    from policyengine_api.services.v2.stored_reports.types import (
        BudgetWindowReportRead,
        BudgetWindowReportSummaryRead,
        ReportRead,
        ReportSummaryRead,
        StoredReportRead,
        StoredReportSummaryRead,
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


class BudgetWindowYearItem(ReportRunItem):
    """One year of a budget-window run: the report run calculating that year.

    Its fields are a report run's, as ``ReportRunItem`` describes them. A
    year still waiting to start is ``pending``, and one the window failed
    before it started is ``failed``, its ``error_message`` saying so.
    """

    year: int


class BudgetWindowRunItem(StrictReportAPIModel):
    """One calculation of a budget window: a report run per year, in year order.

    ``status`` is ``pending`` until a year starts running, ``running`` while
    its years run, ``failed`` once a year has failed, with ``error_message``
    saying which, and ``succeeded`` once every year has. ``trigger`` is
    ``initial`` for the run the report's creation started, and
    ``recalculate`` says whether its years calculate their
    simulations again rather than reusing successful runs.
    ``country_package_version`` and ``policyengine_version`` are the versions
    its years run on, null for a run with no year.
    """

    id: UUID
    status: Literal["pending", "running", "succeeded", "failed"]
    trigger: Literal["initial", "manual", "system"]
    recalculate: bool
    country_package_version: str | None
    policyengine_version: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    years: list[BudgetWindowYearItem]


class BudgetWindowReportSummaryItem(StrictReportAPIModel):
    """A budget window: a baseline and a reform simulation compared in each year.

    The window is ``budget_window_size`` years from ``year``, in the region
    and dataset named. ``status`` is the newest run's, or ``not_run`` for a
    report with no run. ``run`` is the newest budget-window run, whatever its
    status and versions, with its years; ``current_versions`` are the
    versions the Public API runs now, so a newest run on other versions is
    out of date. ``options`` are the options the report was created with.
    """

    id: UUID
    country_id: str
    kind: Literal["budget_window"]
    label: str
    description: str | None
    year: int | None
    budget_window_size: int
    region_code: str | None
    dataset_name: str | None
    baseline_simulation: ReportSimulationItem | None
    reform_simulation: ReportSimulationItem | None
    options: dict[str, JsonValue]
    created_at: datetime
    status: Literal["not_run", "pending", "running", "succeeded", "failed"]
    run: BudgetWindowRunItem | None
    current_versions: PackageVersionsItem

    @classmethod
    def from_summary(
        cls, read: BudgetWindowReportSummaryRead
    ) -> BudgetWindowReportSummaryItem:
        """Build the summary from the service's read, without a result."""
        return cls.model_validate(read)


class BudgetWindowReportItem(BudgetWindowReportSummaryItem):
    """A budget window with its newest run's result.

    ``result`` is the budget-window result, in the format the app reads
    today: each year's budget figures, in year order, and their totals. It is
    there once the newest run has succeeded, and null otherwise.
    """

    result: BudgetWindowResult | None

    @classmethod
    def from_read(cls, read: BudgetWindowReportRead) -> BudgetWindowReportItem:
        """Build the item from the service's read, with its result."""
        return cls.model_validate(read)


def report_item(read: StoredReportRead) -> ReportItem | BudgetWindowReportItem:
    """Build the item of the report's kind from the service's read."""
    if read.kind == "budget_window":
        return BudgetWindowReportItem.from_read(read)
    return ReportItem.from_read(read)


def report_summary_item(
    read: StoredReportSummaryRead,
) -> ReportSummaryItem | BudgetWindowReportSummaryItem:
    """Build the summary of the report's kind from the service's read."""
    if read.kind == "budget_window":
        return BudgetWindowReportSummaryItem.from_summary(read)
    return ReportSummaryItem.from_summary(read)


class ReportDetailResult(StrictReportAPIModel):
    """Result holding one report in ``item``; its ``kind`` says which model it is."""

    item: Annotated[ReportItem | BudgetWindowReportItem, Field(discriminator="kind")]


class ReportListResult(StrictReportAPIModel):
    """The listed reports in ``items``, in the order named, without results."""

    items: list[
        Annotated[
            ReportSummaryItem | BudgetWindowReportSummaryItem,
            Field(discriminator="kind"),
        ]
    ]


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

    The message gives the service's status and code. ``report_id`` names the
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
        "report, which this route does not read yet."
    ),
    500: error_response(
        "The newest run succeeded but its stored result cannot be read (for a "
        "budget window, a year has no succeeded run or no budget figures), or "
        "the operation could not be completed."
    ),
}
CREATE_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: error_response("The body and query name different countries."),
    404: error_response("A policy the report names is not stored in the country."),
    413: error_response("The request body exceeds 16 KiB."),
    422: {
        "model": V2MissingParametersErrorResponse | V2ErrorResponse,
        "description": (
            "The request does not match the schema (such as a budget window of "
            "fewer than 1 or more than 75 years, or one ending after 2200); the "
            "country has no economy "
            "reports (such as a household-only country); a policy the report "
            "names sets parameters the running catalog version does not have "
            "(code missing_parameters, which names them; the baseline's policy is "
            "checked first); or the simulation service cannot run the report: its "
            "422, or its 400 for a region, dataset or dynamic it does not have. The "
            "message says which; for the simulation service's refusal, it gives "
            "the service's code, when it gave one, and its reason, but not its "
            "status."
        ),
    },
    502: {
        "model": V2ErrorResponse | CreatedReportUnreadableResponse,
        "description": (
            "The simulation service may have created the report, but its answer does "
            "not say so. The answer was lost after the request may have reached it, or "
            "a proxy in front of it answered 502 or 504 in its place: the message says "
            "the service may have received the request, but its answer was lost. Or it "
            "failed (500), answered 503 in a shape the Public API cannot read or "
            "naming only another record, or answered a status the Public API does not "
            "expect, which its route may answer after writing rows: the message says "
            "it may have created the report, but failed, with its status and code but "
            "not its reason. Either message asks the caller to submit the report "
            "again, which creates a second report if the first request went through. "
            "Or it created the report, but its answer cannot be read. Or it created "
            "the report, but the report cannot be read back: the answer gives its "
            "report_id, to read with GET /v2/reports/{report_id} rather than "
            "submitting it again."
        ),
    },
    503: {
        "model": V2ErrorResponse | UnavailableAfterReportCreatedResponse,
        "description": (
            "The simulation service created nothing: it cannot be reached or is not "
            "configured; it answered a readable 503 naming no record, and the message "
            "gives its status and code; it answered a 400 naming no region, dataset or "
            "dynamic of the caller's (such as a catalog version missing while a "
            "release deploys), and the message gives its code and reason; it "
            "answered 400 or 422 in a shape the Public API cannot read; or it answered "
            "401, 403, 404, 405, 413 or 429, which are sent before its route runs. Or "
            "the v2 database, or the catalog the policies are checked against, cannot "
            "be read. Or the service created the report, then "
            "Modal refused the run's call and the service failed the run: its 503 "
            "named the report, with its status and code, and the answer gives its "
            "report_id."
        ),
    },
}
