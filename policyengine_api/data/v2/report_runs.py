"""Durable report-definition and report-run operations for API v2-alpha."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS, POLICYENGINE_VERSION
from policyengine_api.data.v2.models import (
    Report,
    ReportRun,
    ReportRunStatus,
    ReportRunTrigger,
)
from policyengine_api.data.v2.models.base import utc_now


class ReportNotFoundError(LookupError):
    """Raised when a requested durable report does not exist."""


class ReportRunNotFoundError(LookupError):
    """Raised when a requested durable report run does not exist."""


class ReportTypeImmutableError(ValueError):
    """Raised when a report type change would reinterpret existing runs."""


class ReportRunStateError(ValueError):
    """Raised when a worker transition is invalid for the durable run."""


def _locked_report(session: Session, report_id: UUID) -> Report:
    # SQLModel's select remains the query surface. Row locking is the bounded
    # SQLAlchemy capability needed to serialize first-run/type updates.
    statement = select(Report).where(Report.id == report_id).with_for_update()
    report = session.exec(statement).one_or_none()
    if report is None:
        raise ReportNotFoundError(f"report {report_id} does not exist")
    return report


def set_report_type(
    session: Session,
    *,
    report_id: UUID,
    report_type: str | None,
) -> Report:
    """Set a report's optional type only while it has no execution history."""

    report = _locked_report(session, report_id)
    if report.type == report_type:
        return report

    existing_run_id = session.exec(
        select(ReportRun.id).where(ReportRun.report_id == report_id).limit(1)
    ).first()
    if existing_run_id is not None:
        raise ReportTypeImmutableError(
            "report type is immutable after the first report run"
        )

    report.type = report_type
    session.add(report)
    session.flush()
    return report


def create_report_run(
    session: Session,
    *,
    report_id: UUID,
    country_package_version: str,
    policyengine_version: str,
    trigger: ReportRunTrigger,
    idempotency_key: UUID | None = None,
) -> ReportRun:
    """Create one run, or return the run for a retried idempotent request."""

    _locked_report(session, report_id)
    if trigger is ReportRunTrigger.MANUAL and idempotency_key is None:
        raise ValueError("manual report reruns require an idempotency key")
    if not country_package_version or not policyengine_version:
        raise ValueError("report run package versions must be non-empty")

    run = ReportRun(
        report_id=report_id,
        country_package_version=country_package_version,
        policyengine_version=policyengine_version,
        trigger=trigger,
        idempotency_key=idempotency_key,
    )
    if idempotency_key is None:
        session.add(run)
        session.flush()
        return run

    try:
        # The report-scoped unique constraint is authoritative under races.
        # A savepoint contains the expected conflict without rolling back
        # unrelated caller work in the surrounding transaction.
        with session.begin_nested():
            session.add(run)
            session.flush()
    except IntegrityError:
        existing = session.exec(
            select(ReportRun).where(
                ReportRun.report_id == report_id,
                ReportRun.idempotency_key == idempotency_key,
            )
        ).one_or_none()
        if existing is None:
            raise
        return existing
    return run


def begin_report_run(
    session: Session,
    *,
    report_run_id: UUID,
    started_at: datetime | None = None,
) -> ReportRun:
    """Start or resume the same pending/running durable run after worker retry."""

    run = session.exec(
        select(ReportRun).where(ReportRun.id == report_run_id).with_for_update()
    ).one_or_none()
    if run is None:
        raise ReportRunNotFoundError(f"report run {report_run_id} does not exist")
    if run.status in {ReportRunStatus.SUCCEEDED, ReportRunStatus.FAILED}:
        raise ReportRunStateError("a terminal report run cannot be resumed")
    if run.status is ReportRunStatus.PENDING:
        run.status = ReportRunStatus.RUNNING
        run.started_at = started_at or utc_now()
        session.add(run)
        session.flush()
    return run


def complete_report_run(
    session: Session,
    *,
    report_run_id: UUID,
    completed_at: datetime | None = None,
    markdown: str | None = None,
) -> ReportRun:
    """Mark the selected durable run successful without replacing history."""

    run = begin_report_run(session, report_run_id=report_run_id)
    run.status = ReportRunStatus.SUCCEEDED
    run.completed_at = completed_at or utc_now()
    run.markdown = markdown
    run.error_message = None
    session.add(run)
    session.flush()
    return run


def fail_report_run(
    session: Session,
    *,
    report_run_id: UUID,
    error_message: str,
    completed_at: datetime | None = None,
) -> ReportRun:
    """Mark the selected durable run failed without deleting older success."""

    run = begin_report_run(session, report_run_id=report_run_id)
    run.status = ReportRunStatus.FAILED
    run.completed_at = completed_at or utc_now()
    run.error_message = error_message
    session.add(run)
    session.flush()
    return run


def select_current_report_run(
    session: Session,
    *,
    report_id: UUID,
    country_package_versions: Mapping[str, str] = COUNTRY_PACKAGE_VERSIONS,
    policyengine_version: str = POLICYENGINE_VERSION,
) -> ReportRun | None:
    """Select the deterministic current successful run for deployed versions."""

    report = session.get(Report, report_id)
    if report is None:
        raise ReportNotFoundError(f"report {report_id} does not exist")
    country_package_version = country_package_versions.get(report.country)
    if country_package_version is None:
        return None

    statement = (
        select(ReportRun)
        .where(
            ReportRun.report_id == report_id,
            ReportRun.status == ReportRunStatus.SUCCEEDED,
            ReportRun.country_package_version == country_package_version,
            ReportRun.policyengine_version == policyengine_version,
            ReportRun.completed_at.is_not(None),
        )
        .order_by(ReportRun.completed_at.desc(), ReportRun.id.desc())
        .limit(1)
    )
    return session.exec(statement).first()
