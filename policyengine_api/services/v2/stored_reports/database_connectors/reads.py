"""Database reads of v2 reports, their newest runs and budget-window years.

A report's own runs are report runs that are not a year of a budget window;
a budget-window report's are budget-window runs, each with a report run per
year. A report read also says whether it is a local-area report: a UK-wide
or nation report on the dataset its catalog version gives local areas.
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
    RegionType,
    Report,
    ReportRun,
    Simulation,
)
from policyengine_api.services.v2.stored_reports.types import StoredReportRows

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence
    from uuid import UUID

    from sqlalchemy import ColumnElement, Label
    from sqlmodel import Session

# The regions a report on the local-area dataset may cover: UK-wide and the
# nations. A constituency's or local authority's own report is on that
# dataset too, but calculates only its one area.
LOCAL_AREA_REPORT_REGION_TYPES = (RegionType.NATIONAL, RegionType.COUNTRY)


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


def _is_default_dataset_of_a(region_type: RegionType) -> ColumnElement[bool]:
    """Return whether some region of the type has the report's dataset as default."""
    area_region = aliased(Region)
    return (
        select(col(area_region.id))
        .where(
            col(area_region.region_type) == region_type,
            col(area_region.default_dataset_id) == Report.dataset_id,
        )
        .exists()
    )


def _on_local_area_dataset() -> Label[bool]:
    """Label whether the report is a local-area report.

    It is when its region is UK-wide or a nation and its dataset is the one
    its catalog version gives both the constituency and the local-authority
    regions, as the simulation service decides which dataset local areas use.
    A release whose two levels name different datasets has no local-area
    dataset. Datasets belong to one catalog version, as the regions naming
    them do. A report whose region is gone reads NULL, which is not one.
    """
    return and_(
        col(Region.region_type).in_(LOCAL_AREA_REPORT_REGION_TYPES),
        _is_default_dataset_of_a(RegionType.CONSTITUENCY),
        _is_default_dataset_of_a(RegionType.LOCAL_AUTHORITY),
    ).label("on_local_area_dataset")


def read_report_rows(
    session: Session, *, country_id: str, report_ids: Collection[UUID]
) -> list[StoredReportRows]:
    """Return the country's reports among ``report_ids``, in two queries.

    Each comes with its region's code, its dataset's name, whether it is a
    local-area report, its two simulations and its newest run: the run
    created last (ties broken by the larger ID), whatever its status and
    versions. Runs of a budget window's years are not
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
            _on_local_area_dataset(),
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
    years = read_budget_window_years(
        session,
        [window_run.id for *_, window_run in rows if window_run is not None],
    )
    return [
        StoredReportRows(
            report=report,
            region_code=region_code,
            dataset_name=dataset_name,
            on_local_area_dataset=bool(on_local_area_dataset),
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
            on_local_area_dataset,
            baseline,
            reform,
            run,
            window_run,
        ) in rows
    ]


def search_report_ids(
    session: Session, *, country_id: str, dataset_independent_key: str, limit: int
) -> list[UUID]:
    """Return the IDs of the country's reports with the dataset-independent key.

    They are the ``limit`` reports created last, newest first, ties going to
    the larger ID, found through ``ix_reports_dataset_independent_key``.
    """
    statement = (
        select(col(Report.id))
        .where(
            col(Report.country) == country_id,
            col(Report.dataset_independent_key) == dataset_independent_key,
        )
        .order_by(col(Report.created_at).desc(), col(Report.id).desc())
        .limit(limit)
    )
    return list(session.execute(statement).scalars())


def read_budget_window_years(
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
