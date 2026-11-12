"""Convert stored report rows to the reads the report service returns."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.stored_reports.types import (
    BudgetWindowReportRead,
    BudgetWindowReportSummaryRead,
    BudgetWindowRunRead,
    BudgetWindowYearRead,
    ReportRead,
    ReportRunRead,
    ReportSimulationRead,
    ReportSummaryRead,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from uuid import UUID

    from policyengine_api.data.v2.models import (
        BudgetWindowRun,
        Report,
        ReportRun,
        Simulation,
    )
    from policyengine_api.services.v2.simulation_service.types import (
        PackageVersions,
    )
    from policyengine_api.services.v2.stored_reports.budget_window_results import (
        types as window_result_types,
    )
    from policyengine_api.services.v2.stored_reports.economy_results.types import (
        EconomyResult,
    )
    from policyengine_api.services.v2.stored_reports.types import (
        ReportKind,
        StoredReportRows,
    )

# The kinds of report the report routes read; household reports are read
# once their own routes exist.
READABLE_KINDS: frozenset[ReportKind] = frozenset({"economy", "budget_window"})


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


def report_summary_read(
    rows: StoredReportRows, *, current_versions: PackageVersions
) -> ReportSummaryRead:
    """Return an economy report's definition and newest run, without a result."""
    report = rows.report
    run = rows.newest_run
    return ReportSummaryRead(
        id=report.id,
        country_id=report.country,
        kind="economy",
        label=report.label,
        description=report.description,
        year=report.year,
        region_code=rows.region_code,
        dataset_name=rows.dataset_name,
        baseline_simulation=_simulation(rows.baseline_simulation),
        reform_simulation=_simulation(rows.reform_simulation),
        options=dict(report.inputs),
        created_at=report.created_at,
        status="not_run" if run is None else run.status.value,
        run=None if run is None else report_run_read(run),
        current_versions=current_versions,
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


def budget_window_run_read(
    window_run: BudgetWindowRun, years: Sequence[ReportRun]
) -> BudgetWindowRunRead:
    """Return the window run's status, trigger and times, with its years.

    Its versions are its first year's, since the simulation service creates
    every year on one version; a run with no year has none.
    """
    year_reads = tuple(
        BudgetWindowYearRead(**vars(report_run_read(run)), year=run.year)
        for run in years
        if run.year is not None
    )
    first_year = year_reads[0] if year_reads else None
    return BudgetWindowRunRead(
        id=window_run.id,
        status=window_run.status.value,
        trigger=window_run.trigger.value,
        recalculate=window_run.recalculate,
        country_package_version=(
            None if first_year is None else first_year.country_package_version
        ),
        policyengine_version=(
            None if first_year is None else first_year.policyengine_version
        ),
        error_message=window_run.error_message,
        created_at=window_run.created_at,
        started_at=window_run.started_at,
        completed_at=window_run.completed_at,
        years=year_reads,
    )


def budget_window_summary_read(
    rows: StoredReportRows, *, current_versions: PackageVersions
) -> BudgetWindowReportSummaryRead:
    """Return a budget-window report's definition and newest run, without a result.

    Raise ValueError for a report with no window size, which is not a budget
    window.
    """
    report = rows.report
    if report.budget_window_size is None:
        msg = f"Report {report.id} is not a budget window"
        raise ValueError(msg)
    window_run = rows.newest_budget_window_run
    return BudgetWindowReportSummaryRead(
        id=report.id,
        country_id=report.country,
        kind="budget_window",
        label=report.label,
        description=report.description,
        year=report.year,
        budget_window_size=report.budget_window_size,
        region_code=rows.region_code,
        dataset_name=rows.dataset_name,
        baseline_simulation=_simulation(rows.baseline_simulation),
        reform_simulation=_simulation(rows.reform_simulation),
        options=dict(report.inputs),
        created_at=report.created_at,
        status="not_run" if window_run is None else window_run.status.value,
        run=(
            None
            if window_run is None
            else budget_window_run_read(window_run, rows.budget_window_years)
        ),
        current_versions=current_versions,
    )


def budget_window_read(
    rows: StoredReportRows,
    *,
    current_versions: PackageVersions,
    result: window_result_types.BudgetWindowResult | None,
) -> BudgetWindowReportRead:
    """Return a budget-window report with its newest run's result, if it has one."""
    summary = budget_window_summary_read(rows, current_versions=current_versions)
    return BudgetWindowReportRead(**vars(summary), result=result)


def listed_reports(
    rows: Iterable[StoredReportRows], *, report_ids: Sequence[UUID]
) -> list[StoredReportRows]:
    """Return the economy and budget-window reports among ``rows``, as named.

    They are in the order of ``report_ids``. A report named twice is listed
    once, where it is first named; household reports are left out.
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
