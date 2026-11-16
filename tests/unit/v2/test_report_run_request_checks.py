"""Checks on what a report's run request must name, without a database."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from policyengine_api.data.v2.models import ReportRunTrigger
from policyengine_api.services.v2.identity.types import UnauthenticatedPrincipal
from policyengine_api.services.v2.report_run_records.types import ReportRunRequest
from policyengine_api.services.v2.simulation_service.types import (
    EconomyReportCreationInput,
    SubmittedReport,
)
from policyengine_api.services.v2.stored_reports.services import V2StoredReportService
from policyengine_api.services.v2.stored_reports.validators import (
    ReportRunRecordsNotConfiguredError,
)
from tests.unit.v2.stored_report_support import (
    CURRENT_VERSIONS,
    REPORT_ID,
    REPORT_RUN_ID,
)

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from sqlmodel import Session

REQUESTED_AT = datetime(2026, 11, 16, 9, tzinfo=UTC)


@pytest.mark.parametrize(
    "run_ids",
    [{}, {"report_run_id": uuid4(), "budget_window_run_id": uuid4()}],
    ids=["neither run", "both runs"],
)
def test_a_run_request_must_name_exactly_one_run(run_ids: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="report run or a budget-window run"):
        ReportRunRequest(
            country_id="us",
            report_id=REPORT_ID,
            requested_at=REQUESTED_AT,
            trigger=ReportRunTrigger.MANUAL,
            **run_ids,
        )


@dataclass
class CountingDatabaseSession:
    """A database session that counts its opens; reading fails."""

    opened: int = 0

    def read(self) -> AbstractContextManager[Session]:
        self.opened += 1
        msg = "The database was opened"
        raise RuntimeError(msg)


@dataclass
class RecordingSubmissions:
    """The simulation service, recording each report submitted to it."""

    submitted: list[EconomyReportCreationInput] = field(default_factory=list)

    def submit_report(self, report: EconomyReportCreationInput) -> SubmittedReport:
        self.submitted.append(report)
        return SubmittedReport(report_id=REPORT_ID, report_run_id=REPORT_RUN_ID)


def test_a_create_naming_a_user_without_a_run_recorder_is_refused_first() -> None:
    database_session = CountingDatabaseSession()
    submissions = RecordingSubmissions()
    service = V2StoredReportService(
        database_session,
        current_versions=lambda country_id: CURRENT_VERSIONS,
        submissions=submissions,
    )

    with pytest.raises(ReportRunRecordsNotConfiguredError):
        service.create_report(
            EconomyReportCreationInput(
                country_id="us",
                kind="economy",
                year=2026,
                region_code="us",
                baseline={},
                reform={},
            ),
            requester=UnauthenticatedPrincipal(user_id=uuid4()),
        )

    assert submissions.submitted == []
    assert database_session.opened == 0
