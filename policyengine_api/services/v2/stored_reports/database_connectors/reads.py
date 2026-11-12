"""Database reads of v2 reports and their newest runs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import and_, func, select
from sqlalchemy.orm import aliased
from sqlmodel import col

from policyengine_api.data.v2.models import (
    Dataset,
    Region,
    Report,
    ReportRun,
    Simulation,
)
from policyengine_api.services.v2.stored_reports.types import StoredReportRows

if TYPE_CHECKING:
    from collections.abc import Collection
    from uuid import UUID

    from sqlmodel import Session


def read_report_rows(
    session: Session, *, country_id: str, report_ids: Collection[UUID]
) -> list[StoredReportRows]:
    """Return the country's reports among ``report_ids``, in one query.

    Each comes with its region's code, its dataset's name, its two simulations
    and its newest run: the run created last (ties broken by the larger ID),
    whatever its status and versions. Runs of a budget window's years are not
    the report's own runs, so they are left out. Reports of other countries,
    and IDs no report has, are absent from the list, which has no set order.
    """
    run_rank = (
        func.row_number()
        .over(
            partition_by=col(ReportRun.report_id),
            order_by=(col(ReportRun.created_at).desc(), col(ReportRun.id).desc()),
        )
        .label("newest_first")
    )
    ranked_runs = (
        select(ReportRun, run_rank)
        .where(
            col(ReportRun.report_id).in_(report_ids),
            col(ReportRun.budget_window_run_id).is_(None),
        )
        .subquery("ranked_report_runs")
    )
    newest_run = aliased(ReportRun, ranked_runs)
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
        .where(col(Report.country) == country_id, col(Report.id).in_(report_ids))
    )
    return [
        StoredReportRows(
            report=report,
            region_code=region_code,
            dataset_name=dataset_name,
            baseline_simulation=baseline,
            reform_simulation=reform,
            newest_run=run,
        )
        for report, region_code, dataset_name, baseline, reform, run in session.execute(
            statement
        ).all()
    ]
