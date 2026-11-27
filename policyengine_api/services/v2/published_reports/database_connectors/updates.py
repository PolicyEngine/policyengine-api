"""Database updates for published reports."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime

    from sqlmodel import Session

    from policyengine_api.data.v2.models import PublishedReport


def update_publication(
    session: Session,
    publication: PublishedReport,
    *,
    values: dict[str, Any],
    updated_at: datetime,
) -> PublishedReport:
    """Set ``values`` on the published report, changed at ``updated_at``."""
    for name, value in values.items():
        setattr(publication, name, value)
    publication.updated_at = updated_at
    session.add(publication)
    session.flush()
    return publication
