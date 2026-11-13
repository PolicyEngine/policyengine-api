"""Record each user's requests for v2 report runs."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from policyengine_api.services.v2.report_run_records.database_session import (
        ReportRunRecordDatabaseSession,
    )


class ReportRunRecordService:
    """Record the report runs users ask for."""

    def __init__(self, database_session: ReportRunRecordDatabaseSession) -> None:
        """Read and write through ``database_session``."""
        self._database_session = database_session
