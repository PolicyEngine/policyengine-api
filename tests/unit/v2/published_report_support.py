"""Rows and stand-ins for the published-report service tests on SQLite.

SQLite doesn't enforce the v2 foreign keys here, so a test stores only the
rows a published report reads: the owner, the saved report, its report and
the report's runs. The PostgreSQL tests check the keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from policyengine_api.data.v2.models import (
    BudgetWindowRun,
    Report,
    ReportRun,
    ReportRunStatus,
    UserPolicy,
    UserReportAssociation,
)
from policyengine_api.services.v2.identity.services import (
    resolve_principal_user_in_session,
)
from policyengine_api.services.v2.identity.types import UserPrincipal
from policyengine_api.services.v2.published_reports.database_session import (
    PublishedReportDatabaseSession,
)
from policyengine_api.services.v2.published_reports.services import (
    V2PublishedReportService,
)
from tests.unit.v2.stored_report_support import report_read, report_run_read

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

    from policyengine_api.services.v2.stored_reports.types import StoredReportRead

ISSUER = "https://auth.example.test/"
FINISHED_AT = datetime(2026, 11, 20, 9, tzinfo=UTC)
PROVISIONS = [
    {
        "path": "gov.irs.credits.ctc.amount",
        "breadcrumb": "Child Tax Credit amount",
        "unit": "currency-USD",
        "baseline_value": 2000,
        "value": 3000,
    }
]


def author_principal() -> UserPrincipal:
    """Return a new signed-in user's principal."""
    return UserPrincipal(issuer=ISSUER, subject=f"auth0|{uuid4()}")


@dataclass
class RecordingReportReader:
    """Answer each report read as the report service would, and record it."""

    calls: list[dict[str, Any]] = field(default_factory=list)

    def get_report(self, **kwargs: Any) -> StoredReportRead:
        self.calls.append(kwargs)
        return report_read(
            id=kwargs["report_id"],
            country_id=kwargs["country_id"],
            label=None,
            run=report_run_read(id=kwargs["run_id"]),
        )


def published_report_service(
    sessions: sessionmaker[Session], reports: RecordingReportReader | None = None
) -> V2PublishedReportService:
    """Return the service on ``sessions``, reading reports through ``reports``."""
    return V2PublishedReportService(
        PublishedReportDatabaseSession(sessions),
        reports=RecordingReportReader() if reports is None else reports,
    )


@dataclass(frozen=True)
class SavedReportRows:
    """A user's saved report of a stored report, and that user's principal."""

    principal: UserPrincipal
    user_id: UUID
    user_report_id: UUID
    report_id: UUID | None


def store_report(session: Session, *, budget_window_size: int | None = None) -> UUID:
    """Store a US economy report, or a budget window, and return its ID."""
    report = Report(
        country="us",
        tax_benefit_model_id=uuid4(),
        year=2026,
        budget_window_size=budget_window_size,
        inputs={},
    )
    session.add(report)
    session.flush()
    return report.id


def store_saved_report(  # noqa: PLR0913  # the session, then each column a test varies
    session: Session,
    *,
    principal: UserPrincipal | None = None,
    report_id: UUID | None = None,
    legacy_report_id: int | None = None,
    name: str | None = "Expanded child tax credit",
    country_id: str = "us",
    baseline_reform_name: str | None = None,
) -> SavedReportRows:
    """Save a report for the principal's user, provisioning that user."""
    owner = principal or author_principal()
    user_id = resolve_principal_user_in_session(
        session, owner, country_id=country_id
    ).user_id
    baseline_user_policy_id = None
    if baseline_reform_name is not None:
        baseline = UserPolicy(
            user_id=user_id,
            policy_id=uuid4(),
            country_id=country_id,
            name=baseline_reform_name,
        )
        session.add(baseline)
        session.flush()
        baseline_user_policy_id = baseline.id
    stored_report_id = (
        store_report(session)
        if report_id is None and legacy_report_id is None
        else report_id
    )
    saved = UserReportAssociation(
        user_id=user_id,
        report_id=stored_report_id,
        legacy_report_id=legacy_report_id,
        country_id=country_id,
        name=name,
        description="My own notes",
        source_note="From the chat",
        provisions=PROVISIONS,
        user_policy_id=uuid4(),
        baseline_user_policy_id=baseline_user_policy_id,
        last_run_at=FINISHED_AT,
    )
    session.add(saved)
    session.flush()
    return SavedReportRows(
        principal=owner,
        user_id=user_id,
        user_report_id=saved.id,
        report_id=stored_report_id,
    )


def store_report_run(
    session: Session,
    report_id: UUID,
    *,
    status: ReportRunStatus = ReportRunStatus.SUCCEEDED,
    days_later: int = 0,
    budget_window_run_id: UUID | None = None,
) -> UUID:
    """Store a run of the report on .py 4.2.0 and return its ID."""
    finished = status in {ReportRunStatus.SUCCEEDED, ReportRunStatus.FAILED}
    created_at = FINISHED_AT + timedelta(days=days_later)
    run = ReportRun(
        report_id=report_id,
        baseline_simulation_run_id=uuid4(),
        reform_simulation_run_id=uuid4(),
        budget_window_run_id=budget_window_run_id,
        year=None if budget_window_run_id is None else 2026 + days_later,
        country_package_version="1.5.0",
        policyengine_version=f"4.{2 + days_later}.0",
        status=status,
        created_at=created_at,
        completed_at=created_at if finished else None,
    )
    session.add(run)
    session.flush()
    return run.id


def store_budget_window_run(
    session: Session,
    report_id: UUID,
    *,
    status: ReportRunStatus = ReportRunStatus.SUCCEEDED,
) -> UUID:
    """Store a budget-window run of the report, with one year, and return its ID."""
    finished = status in {ReportRunStatus.SUCCEEDED, ReportRunStatus.FAILED}
    window_run = BudgetWindowRun(
        report_id=report_id,
        tax_benefit_model_version_id=uuid4(),
        policyengine_version="4.2.0",
        status=status,
        created_at=FINISHED_AT,
        completed_at=FINISHED_AT if finished else None,
    )
    session.add(window_run)
    session.flush()
    store_report_run(
        session, report_id, status=status, budget_window_run_id=window_run.id
    )
    return window_run.id


def publication_body(run_id: UUID, **changes: Any) -> dict[str, Any]:
    """Return a publication's fields as an author sends them."""
    body: dict[str, Any] = {
        "run_id": str(run_id),
        "summary": "What a larger child tax credit costs and who gains.",
        "author_ids": ["nikhil-woodruff"],
        "tags": ["us", "child-tax-credit"],
        "content": [
            {"type": "markdown", "markdown": "## Why this reform"},
            {"type": "output", "output": "budgetary_impact"},
            {"type": "output", "output": "poverty_impact"},
        ],
        "show_past_versions": False,
    }
    return {**body, **changes}


def without_run(body: dict[str, Any]) -> dict[str, Any]:
    """Return the publication's fields without its run."""
    return {key: value for key, value in body.items() if key != "run_id"}
