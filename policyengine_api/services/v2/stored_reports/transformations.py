"""Convert stored report rows to the reads the report service returns."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.stored_reports.types import (
    HouseholdReportRead,
    HouseholdReportSummaryRead,
    ReportDefinitionRead,
    ReportRead,
    ReportRunRead,
    ReportSimulationRead,
    ReportSummaryRead,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from uuid import UUID

    from policyengine_api.data.v2.models import Report, ReportRun, Simulation
    from policyengine_api.services.v2.simulation_service.types import (
        PackageVersions,
    )
    from policyengine_api.services.v2.stored_reports.economy_results.types import (
        EconomyResult,
    )
    from policyengine_api.services.v2.stored_reports.household_results.types import (
        HouseholdReportResult,
    )
    from policyengine_api.services.v2.stored_reports.types import (
        ReportKind,
        StoredReportRows,
    )

# The kinds of report the report routes read; budget windows are read once
# their own routes exist.
READABLE_KINDS: frozenset[ReportKind] = frozenset({"economy", "household"})


def report_kind(report: Report) -> ReportKind:
    """Return what the report compares, from the columns its kind sets."""
    if report.household_id is not None:
        return "household"
    if report.budget_window_size is not None:
        return "budget_window"
    return "economy"


def report_run_read(run: ReportRun) -> ReportRunRead:
    """Return the run's status, trigger, versions and times."""
    return ReportRunRead(
        id=run.id,
        status=run.status.value,
        trigger=run.trigger.value,
        country_package_version=run.country_package_version,
        policyengine_version=run.policyengine_version,
        baseline_simulation_run_id=run.baseline_simulation_run_id,
        reform_simulation_run_id=run.reform_simulation_run_id,
        error_message=run.error_message,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


def _simulation(simulation: Simulation | None) -> ReportSimulationRead | None:
    if simulation is None:
        return None
    return ReportSimulationRead(
        id=simulation.id,
        policy_id=simulation.policy_id,
        dynamic_id=simulation.dynamic_id,
    )


def _report_definition(
    rows: StoredReportRows, *, current_versions: PackageVersions
) -> ReportDefinitionRead:
    """Return what every report's read gives: its definition and current versions."""
    report = rows.report
    return ReportDefinitionRead(
        id=report.id,
        country_id=report.country,
        label=report.label,
        description=report.description,
        year=report.year,
        region_code=rows.region_code,
        dataset_name=rows.dataset_name,
        baseline_simulation=_simulation(rows.baseline_simulation),
        reform_simulation=_simulation(rows.reform_simulation),
        options=dict(report.inputs),
        created_at=report.created_at,
        current_versions=current_versions,
    )


def report_summary_read(
    rows: StoredReportRows, *, current_versions: PackageVersions
) -> ReportSummaryRead:
    """Return an economy report's definition and newest run, without a result."""
    run = rows.newest_run
    return ReportSummaryRead(
        **vars(_report_definition(rows, current_versions=current_versions)),
        kind="economy",
        status="not_run" if run is None else run.status.value,
        run=None if run is None else report_run_read(run),
    )


def report_read(
    rows: StoredReportRows,
    *,
    current_versions: PackageVersions,
    result: EconomyResult | None,
) -> ReportRead:
    """Return an economy report with its newest run's result, if it has one."""
    summary = report_summary_read(rows, current_versions=current_versions)
    return ReportRead(**vars(summary), result=result)


def household_report_summary_read(
    rows: StoredReportRows, *, current_versions: PackageVersions
) -> HouseholdReportSummaryRead:
    """Return a household report's definition and newest run, without a result.

    Raise ValueError for a report naming no household, which is not a
    household report.
    """
    report = rows.report
    if report.household_id is None:
        msg = f"Report {report.id} is not a household report"
        raise ValueError(msg)
    run = rows.newest_run
    return HouseholdReportSummaryRead(
        **vars(_report_definition(rows, current_versions=current_versions)),
        kind="household",
        household_id=report.household_id,
        status="not_run" if run is None else run.status.value,
        run=None if run is None else report_run_read(run),
    )


def household_report_read(
    rows: StoredReportRows,
    *,
    current_versions: PackageVersions,
    result: HouseholdReportResult | None,
) -> HouseholdReportRead:
    """Return a household report with its calculated households, if it has them."""
    summary = household_report_summary_read(rows, current_versions=current_versions)
    return HouseholdReportRead(**vars(summary), result=result)


def listed_reports(
    rows: Iterable[StoredReportRows], *, report_ids: Sequence[UUID]
) -> list[StoredReportRows]:
    """Return the economy and household reports among ``rows``, as named.

    They are in the order of ``report_ids``. A report named twice is listed
    once, where it is first named; budget windows are left out.
    """
    by_id = {
        stored.report.id: stored
        for stored in rows
        if report_kind(stored.report) in READABLE_KINDS
    }
    listed: list[StoredReportRows] = []
    for report_id in dict.fromkeys(report_ids):
        stored = by_id.get(report_id)
        if stored is not None:
            listed.append(stored)
    return listed
