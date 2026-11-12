"""Database reads of v2 reports and their newest runs.

A report's own runs are report runs that are not a year of a budget window;
a budget-window report's are budget-window runs, each with a report run per
year.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import and_, func, select
from sqlalchemy.orm import aliased
from sqlmodel import col

from policyengine_api.data.v2.models import (
    BudgetWindowRun,
    Dataset,
    Region,
    Report,
    ReportRun,
    Simulation,
)
from policyengine_api.services.v2.stored_reports.types import StoredReportRows

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence
    from uuid import UUID

    from sqlalchemy import Label
    from sqlmodel import Session


def _newest_first(run_model: type[ReportRun | BudgetWindowRun]) -> Label[int]:
    """Return a label numbering each report's runs from 1, newest first.

    The newest is the run created last, ties going to the larger ID.
    """
    return (
        func.row_number()
        .over(
            partition_by=col(run_model.report_id),
            order_by=(col(run_model.created_at).desc(), col(run_model.id).desc()),
        )
        .label("newest_first")
    )


def read_report_rows(
    session: Session, *, country_id: str, report_ids: Collection[UUID]
) -> list[StoredReportRows]:
    """Return the country's reports among ``report_ids``, in two queries.

    Each comes with its region's code, its dataset's name, its two simulations
    and its newest run: the run created last (ties broken by the larger ID),
    whatever its status and versions. Runs of a budget window's years are not
    the report's own runs, so they are left out. Each also comes with its
    newest budget-window run, chosen the same way, and that run's years,
    which a second query reads for every report at once. Reports of other
    countries, and IDs no report has, are absent from the list, which has no
    set order.
    """
    run_rank = _newest_first(ReportRun)
    ranked_runs = (
        select(ReportRun, run_rank)
        .where(
            col(ReportRun.report_id).in_(report_ids),
            col(ReportRun.budget_window_run_id).is_(None),
        )
        .subquery("ranked_report_runs")
    )
    newest_run = aliased(ReportRun, ranked_runs)
    ranked_window_runs = (
        select(BudgetWindowRun, _newest_first(BudgetWindowRun))
        .where(col(BudgetWindowRun.report_id).in_(report_ids))
        .subquery("ranked_budget_window_runs")
    )
    newest_window_run = aliased(BudgetWindowRun, ranked_window_runs)
    baseline_simulation = aliased(Simulation)
    reform_simulation = aliased(Simulation)
    statement = (
        select(
            Report,
            col(Region.code),
            col(Dataset.name),
            baseline_simulation,
            reform_simulation,
            newest_run,
            newest_window_run,
        )
        .outerjoin(Region, col(Region.id) == Report.region_id)
        .outerjoin(Dataset, col(Dataset.id) == Report.dataset_id)
        .outerjoin(
            baseline_simulation,
            col(baseline_simulation.id) == Report.baseline_simulation_id,
        )
        .outerjoin(
            reform_simulation, col(reform_simulation.id) == Report.reform_simulation_id
        )
        .outerjoin(
            newest_run,
            and_(
                col(newest_run.report_id) == Report.id,
                ranked_runs.c.newest_first == 1,
            ),
        )
        .outerjoin(
            newest_window_run,
            and_(
                col(newest_window_run.report_id) == Report.id,
                ranked_window_runs.c.newest_first == 1,
            ),
        )
        .where(col(Report.country) == country_id, col(Report.id).in_(report_ids))
    )
    rows = session.execute(statement).all()
    years = _budget_window_years(
        session,
        [window_run.id for *_, window_run in rows if window_run is not None],
    )
    return [
        StoredReportRows(
            report=report,
            region_code=region_code,
            dataset_name=dataset_name,
            baseline_simulation=baseline,
            reform_simulation=reform,
            newest_run=run,
            newest_budget_window_run=window_run,
            budget_window_years=(
                () if window_run is None else years.get(window_run.id, ())
            ),
        )
        for (
            report,
            region_code,
            dataset_name,
            baseline,
            reform,
            run,
            window_run,
        ) in rows
    ]


def _budget_window_years(
    session: Session, budget_window_run_ids: Sequence[UUID]
) -> dict[UUID, tuple[ReportRun, ...]]:
    """Return each budget-window run's year report runs, in year order."""
    if not budget_window_run_ids:
        return {}
    statement = (
        select(ReportRun)
        .where(col(ReportRun.budget_window_run_id).in_(budget_window_run_ids))
        .order_by(col(ReportRun.year), col(ReportRun.id))
    )
    years: dict[UUID, list[ReportRun]] = {}
    for year_run in session.execute(statement).scalars():
        if year_run.budget_window_run_id is not None:
            years.setdefault(year_run.budget_window_run_id, []).append(year_run)
    return {window_run_id: tuple(runs) for window_run_id, runs in years.items()}
