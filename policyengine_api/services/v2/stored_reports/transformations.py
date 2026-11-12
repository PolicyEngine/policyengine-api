"""Convert stored report rows to the reads the report service returns."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.stored_reports.types import (
    ReportRead,
    ReportRunRead,
    ReportRunsRead,
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
    from policyengine_api.services.v2.stored_reports.types import (
        ReportKind,
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


def listed_economy_reports(
    rows: Iterable[StoredReportRows], *, report_ids: Sequence[UUID]
) -> list[StoredReportRows]:
    """Return the economy reports among ``rows`` in the order of ``report_ids``.

    A report named twice is listed once, where it is first named; reports of
    other kinds are left out.
    """
    by_id = {
        stored.report.id: stored
        for stored in rows
        if report_kind(stored.report) == "economy"
    }
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
    current_versions: PackageVersions,
) -> ReportRunsRead:
    """Return an economy report's runs, in the order given, and the current versions."""
    return ReportRunsRead(
        report_id=rows.report.id,
        kind="economy",
        runs=tuple(report_run_read(run) for run in runs),
        current_versions=current_versions,
    )
