"""Database reads for published reports and the runs they show."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlmodel import Session, col

from policyengine_api.data.v2.models import (
    BudgetWindowRun,
    PublishedReport,
    PublishedReportVersion,
    Report,
    ReportRun,
    UserReportAssociation,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from policyengine_api.data.v2.models import ReportRunStatus


def read_publication_row(
    session: Session, *, user_report_id: UUID
) -> PublishedReport | None:
    """Return the saved report's published report, or None."""
    return session.get(PublishedReport, user_report_id)


def lock_publication_row(
    session: Session, *, user_report_id: UUID
) -> PublishedReport | None:
    """Return the saved report's published report, locked until the transaction ends.

    An edit, a move and a withdrawal each lock it, so none of them changes a
    page another has just withdrawn.
    """
    return session.scalar(
        select(PublishedReport)
        .where(col(PublishedReport.user_report_id) == user_report_id)
        .with_for_update()
    )


def lock_owned_user_report_row(
    session: Session, *, user_id: UUID, country_id: str, user_report_id: UUID
) -> UserReportAssociation | None:
    """Return the user's saved report, locked until the transaction ends.

    A publish locks it, as the saved report's edit does, so its name and
    report can't change while the publish reads them.
    """
    return session.scalar(
        select(UserReportAssociation)
        .where(
            col(UserReportAssociation.id) == user_report_id,
            col(UserReportAssociation.country_id) == country_id,
            col(UserReportAssociation.user_id) == user_id,
        )
        .with_for_update()
    )


def read_published_report_rows(
    session: Session, *, country_id: str, user_report_id: UUID
) -> tuple[PublishedReport, UserReportAssociation] | None:
    """Return a published report of the country with its saved report, or None."""
    row = session.execute(
        select(PublishedReport, UserReportAssociation)
        .join(
            UserReportAssociation,
            col(UserReportAssociation.id) == col(PublishedReport.user_report_id),
        )
        .where(
            col(PublishedReport.user_report_id) == user_report_id,
            col(UserReportAssociation.country_id) == country_id,
        )
    ).one_or_none()
    return None if row is None else (row[0], row[1])


def read_publication_version_rows(
    session: Session, *, user_report_id: UUID
) -> list[tuple[PublishedReportVersion, ReportRun | None]]:
    """Return the published report's versions, newest first, each with its run.

    A version of an economy or household report comes with its report run;
    a budget window's comes with None, for ``read_window_first_years``.
    """
    rows = session.execute(
        select(PublishedReportVersion, ReportRun)
        .outerjoin(
            ReportRun,
            col(ReportRun.id) == col(PublishedReportVersion.report_run_id),
        )
        .where(col(PublishedReportVersion.user_report_id) == user_report_id)
        .order_by(
            col(PublishedReportVersion.created_at).desc(),
            col(PublishedReportVersion.id).desc(),
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


def read_window_first_years(
    session: Session, *, budget_window_run_ids: Sequence[UUID]
) -> dict[UUID, ReportRun]:
    """Return each budget-window run's first year's report run, by window run.

    The simulation service creates every year of a window run on one set of
    versions, so its first year's are the window run's. A window run with no
    year is left out.
    """
    if not budget_window_run_ids:
        return {}
    years = session.scalars(
        select(ReportRun)
        .where(col(ReportRun.budget_window_run_id).in_(budget_window_run_ids))
        .order_by(col(ReportRun.budget_window_run_id), col(ReportRun.year))
    ).all()
    first_years: dict[UUID, ReportRun] = {}
    for year in years:
        if year.budget_window_run_id is not None:
            first_years.setdefault(year.budget_window_run_id, year)
    return first_years


def read_report_row(session: Session, *, report_id: UUID) -> Report | None:
    """Return the report, or None."""
    return session.get(Report, report_id)


def read_report_run_status(
    session: Session, *, report_id: UUID, run_id: UUID
) -> ReportRunStatus | None:
    """Return the status of the report's own report run, or None.

    A year of a budget-window run is that window run's, not the report's.
    """
    return session.scalar(
        select(col(ReportRun.status)).where(
            col(ReportRun.id) == run_id,
            col(ReportRun.report_id) == report_id,
            col(ReportRun.budget_window_run_id).is_(None),
        )
    )


def read_budget_window_run_status(
    session: Session, *, report_id: UUID, run_id: UUID
) -> ReportRunStatus | None:
    """Return the status of the report's budget-window run, or None."""
    return session.scalar(
        select(col(BudgetWindowRun.status)).where(
            col(BudgetWindowRun.id) == run_id,
            col(BudgetWindowRun.report_id) == report_id,
        )
    )
