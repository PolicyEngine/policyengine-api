"""Convert stored report rows to the reads the report service returns."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.stored_reports.types import (
    BudgetWindowReportRead,
    BudgetWindowReportSummaryRead,
    BudgetWindowRunRead,
    BudgetWindowRunsRead,
    BudgetWindowYearRead,
    HouseholdReportRead,
    HouseholdReportSummaryRead,
    ReportDefinitionRead,
    ReportRead,
    ReportRunRead,
    ReportRunsRead,
    ReportSimulationRead,
    ReportSummaryRead,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
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
    from policyengine_api.services.v2.stored_reports.household_results.types import (
        HouseholdReportFailure,
        HouseholdReportResult,
    )
    from policyengine_api.services.v2.stored_reports.types import (
        ReportKind,
        ReportRunsKind,
        ReportStatusName,
        StoredReportRows,
    )


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
        label=rows.saved_report_name,
        description=rows.saved_report_description,
        year=report.year,
        baseline_simulation=_simulation(rows.baseline_simulation),
        reform_simulation=_simulation(rows.reform_simulation),
        options=dict(report.inputs),
        created_at=report.created_at,
        current_versions=current_versions,
    )


def _run_and_status(
    rows: StoredReportRows,
) -> tuple[ReportStatusName, ReportRunRead | None]:
    """Return the report's status and the run read: ``not_run`` and None without one."""
    run = rows.run
    if run is None:
        return "not_run", None
    return run.status.value, report_run_read(run)


def report_summary_read(
    rows: StoredReportRows, *, current_versions: PackageVersions
) -> ReportSummaryRead:
    """Return an economy report's definition and newest run, without a result."""
    status, run = _run_and_status(rows)
    return ReportSummaryRead(
        **vars(_report_definition(rows, current_versions=current_versions)),
        kind="economy",
        region_code=rows.region_code,
        dataset_name=rows.dataset_name,
        status=status,
        run=run,
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
    status, run = _run_and_status(rows)
    return HouseholdReportSummaryRead(
        **vars(_report_definition(rows, current_versions=current_versions)),
        kind="household",
        household_id=report.household_id,
        status=status,
        run=run,
    )


def household_report_read(
    rows: StoredReportRows,
    *,
    current_versions: PackageVersions,
    result: HouseholdReportResult | None,
    failure: HouseholdReportFailure | None,
) -> HouseholdReportRead:
    """Return a household report with its newest run's outcome, if it has one."""
    summary = household_report_summary_read(rows, current_versions=current_versions)
    return HouseholdReportRead(**vars(summary), result=result, failure=failure)


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
    window_run = rows.budget_window_run
    return BudgetWindowReportSummaryRead(
        **vars(_report_definition(rows, current_versions=current_versions)),
        kind="budget_window",
        region_code=rows.region_code,
        dataset_name=rows.dataset_name,
        budget_window_size=report.budget_window_size,
        status="not_run" if window_run is None else window_run.status.value,
        run=(
            None
            if window_run is None
            else budget_window_run_read(window_run, rows.budget_window_years)
        ),
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
    """Return the reports among ``rows`` in the order of ``report_ids``.

    A report named twice is listed once, where it is first named.
    """
    by_id = {stored.report.id: stored for stored in rows}
    listed: list[StoredReportRows] = []
    for report_id in dict.fromkeys(report_ids):
        stored = by_id.get(report_id)
        if stored is not None:
            listed.append(stored)
    return listed


def report_policy_ids(rows: StoredReportRows) -> tuple[UUID | None, ...]:
    """Return the policies of the report's simulations, baseline first.

    A simulation of current law, or one that is gone, names none.
    """
    return tuple(
        None if simulation is None else simulation.policy_id
        for simulation in (rows.baseline_simulation, rows.reform_simulation)
    )


def report_runs_read(
    rows: StoredReportRows,
    runs: Iterable[ReportRun],
    *,
    kind: ReportRunsKind,
    current_versions: PackageVersions,
) -> ReportRunsRead:
    """Return the report's runs as ``kind``'s, in the order given, with the versions."""
    return ReportRunsRead(
        report_id=rows.report.id,
        kind=kind,
        runs=tuple(report_run_read(run) for run in runs),
        current_versions=current_versions,
    )


def budget_window_runs_read(
    rows: StoredReportRows,
    window_runs: Iterable[BudgetWindowRun],
    years: Mapping[UUID, Sequence[ReportRun]],
    *,
    current_versions: PackageVersions,
) -> BudgetWindowRunsRead:
    """Return a budget window's runs, in the order given, and the current versions.

    ``years`` holds each window run's year report runs, in year order; a run
    with none has no years.
    """
    return BudgetWindowRunsRead(
        report_id=rows.report.id,
        kind="budget_window",
        runs=tuple(
            budget_window_run_read(window_run, years.get(window_run.id, ()))
            for window_run in window_runs
        ),
        current_versions=current_versions,
    )
