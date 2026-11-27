"""Database inserts for published reports and their versions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from policyengine_api.data.v2.models import PublishedReport, PublishedReportVersion

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.services.v2.published_reports.types import PublishedRun


def create_publication(
    session: Session,
    *,
    user_report_id: UUID,
    report_id: UUID,
    values: dict[str, Any],
    published_at: datetime,
) -> PublishedReport:
    """Insert the saved report's published report, with ``values`` as its fields."""
    publication = PublishedReport(
        user_report_id=user_report_id,
        report_id=report_id,
        created_at=published_at,
        updated_at=published_at,
        **values,
    )
    session.add(publication)
    session.flush()
    return publication


def create_publication_version(
    session: Session,
    *,
    user_report_id: UUID,
    run: PublishedRun,
    published_at: datetime,
) -> PublishedReportVersion:
    """Insert a version of the published report, showing ``run``."""
    version = PublishedReportVersion(
        user_report_id=user_report_id,
        report_run_id=run.report_run_id,
        budget_window_run_id=run.budget_window_run_id,
        created_at=published_at,
    )
    session.add(version)
    session.flush()
    return version
