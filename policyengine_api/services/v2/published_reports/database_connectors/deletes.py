"""Database deletes for published reports."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete
from sqlmodel import col

from policyengine_api.data.v2.models import PublishedReportVersion

if TYPE_CHECKING:
    from sqlmodel import Session

    from policyengine_api.data.v2.models import PublishedReport


def delete_publication(session: Session, publication: PublishedReport) -> None:
    """Delete the published report's versions, then the published report.

    The versions' foreign key would delete them with it; deleting them
    first leaves none behind where foreign keys aren't enforced.
    """
    session.execute(
        delete(PublishedReportVersion).where(
            col(PublishedReportVersion.user_report_id) == publication.user_report_id
        )
    )
    session.delete(publication)
    session.flush()
