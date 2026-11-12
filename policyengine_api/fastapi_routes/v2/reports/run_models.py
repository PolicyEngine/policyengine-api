"""Strict HTTP models of a v2 report's runs: running it again and listing them."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from pydantic import StrictBool

from policyengine_api.fastapi_routes.v2.errors_support import (
    V2ErrorResponse,
    V2MissingParametersErrorResponse,
)
from policyengine_api.fastapi_routes.v2.reports.response_models import (
    PackageVersionsItem,
    ReportRunItem,
    ReportSuccessResponse,
    StrictReportAPIModel,
)
from policyengine_api.fastapi_routes.v2.simulation_resources_support import (
    error_response,
)
from policyengine_api.services.v2.simulation_service.types import (
    StrictSubmissionModel,
)

if TYPE_CHECKING:
    from policyengine_api.services.v2.stored_reports.types import ReportRunsRead


class ReportRerunRequest(StrictSubmissionModel):
    """Run a stored report again on the simulation service's current versions.

    Without ``force`` (``{}``), each side reuses a run of its own simulation
    that succeeded on those versions; with it, both simulations are
    calculated again. The new run is kept beside every earlier one.
    """

    force: StrictBool = False


class ReportRunListResult(StrictReportAPIModel):
    """A report's runs in ``items``, newest first, whatever their status.

    Each run names the country package and PolicyEngine.py versions it ran
    on; ``current_versions`` are those the Public API runs now, so a run on
    other versions is out of date.
    """

    report_id: UUID
    kind: Literal["economy"]
    items: list[ReportRunItem]
    current_versions: PackageVersionsItem

    @classmethod
    def from_read(cls, read: ReportRunsRead) -> ReportRunListResult:
        """Build the list from the service's read of the report's runs."""
        return cls(
            report_id=read.report_id,
            kind=read.kind,
            items=[ReportRunItem.model_validate(run) for run in read.runs],
            current_versions=PackageVersionsItem.model_validate(read.current_versions),
        )


class ReportRunListResponse(ReportSuccessResponse[ReportRunListResult]):
    """Success response holding a report's runs."""


class ReportRerunConflictResponse(V2ErrorResponse):
    """The 409 answer when the simulation service will not run the report again now.

    The message gives the service's code and reason: ``run_in_progress``,
    when the report has a run pending or running, which ``run_id`` names, or
    ``rerun_not_supported`` for a report it does not run again, such as one
    whose simulation, region or dataset is gone. ``run_id`` is null when the
    service named no run.
    """

    run_id: UUID | None


class RerunReportUnreadableResponse(V2ErrorResponse):
    """The 502 answer when the report cannot be read back after its new run started.

    The simulation service started the run, so the caller reads the report
    with ``GET /v2/reports/{report_id}`` rather than running it again.
    """

    report_id: UUID


NOT_FOUND = "No report has this ID in this country."
OTHER_KIND = (
    "or the report is a household report or a budget window, whose runs these "
    "routes do not start or list yet"
)
RUN_LIST_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: error_response(NOT_FOUND),
    422: error_response(f"The request does not match the schema, {OTHER_KIND}."),
}
RERUN_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: error_response(
        f"{NOT_FOUND} Or a policy a simulation of the report names is no longer "
        "stored in the country."
    ),
    409: {
        "model": ReportRerunConflictResponse,
        "description": (
            "The simulation service will not run the report again now, and "
            "started nothing: the report has a run pending or running "
            "(run_in_progress), which run_id names, or it is one the service "
            "does not run again (rerun_not_supported)."
        ),
    },
    413: error_response("The request body exceeds 16 KiB."),
    422: {
        "model": V2MissingParametersErrorResponse | V2ErrorResponse,
        "description": (
            f"The request does not match the schema, {OTHER_KIND}; the country has "
            "no economy reports; a policy of the report's simulations sets "
            "parameters the running catalog version does not have (code "
            "missing_parameters, which names them); or the simulation service "
            "cannot run the report as stored: its 422, or its 400 for a region, "
            "dataset or dynamic the report names that the current catalog version "
            "does not have, with its code and reason."
        ),
    },
    502: {
        "model": V2ErrorResponse | RerunReportUnreadableResponse,
        "description": (
            "The simulation service may have started a new run, but its answer "
            "does not say so: its answer was lost, a proxy answered in its place, "
            "it failed (500), or it answered in a shape or status the Public API "
            "does not expect. The message asks the caller to read the report to "
            "see whether it has a new run before running it again; while that "
            "run is pending or running, running it again answers 409. Or it "
            "started the run, but the report cannot be read back: the answer "
            "gives its report_id."
        ),
    },
    503: error_response(
        "The simulation service started nothing that runs: it cannot be reached "
        "or is not configured; it answered a readable 503, and the message gives "
        "its status and code, and names the new run it failed when Modal refused "
        "the run's call; it answered a 400 about its own state rather than a row "
        "the report names (such as a catalog version missing while a release "
        "deploys), and the message gives its code and reason; it answered 400, "
        "409 or 422 in a shape the Public API cannot read; or it answered 401, "
        "403, 404, 405, 413 or 429, which it sends before writing anything. Or "
        "the v2 database, or the catalog the policies are checked against, "
        "cannot be read."
    ),
}
