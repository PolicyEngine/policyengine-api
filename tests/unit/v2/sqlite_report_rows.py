"""SQLite's copy of the v2 schema, and economy reports stored in it, for read tests.

The simulation service stores these rows in staging and production; here a
test stores them directly and reads them through ``V2StoredReportService``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine

from policyengine_api.data.v2.models import (
    V2_METADATA,
    Report,
    Simulation,
    SimulationType,
)
from policyengine_api.services.v2.simulation_service.types import PackageVersions
from policyengine_api.services.v2.stored_reports.database_session import (
    StoredReportDatabaseSession,
)
from policyengine_api.services.v2.stored_reports.services import V2StoredReportService

if TYPE_CHECKING:
    from collections.abc import Iterator

STORED_AT = datetime(2026, 11, 14, 9, tzinfo=UTC)
CURRENT_VERSIONS = PackageVersions(
    country_package_version="2.1.0", policyengine_version="6.17.1"
)


def sqlite_sessions() -> Iterator[sessionmaker[Session]]:
    """Yield sessions of a new in-memory v2 schema, and dispose of it after."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    V2_METADATA.create_all(engine)
    try:
        yield sessionmaker(engine, class_=Session, expire_on_commit=False)
    finally:
        engine.dispose()


def report_service(sessions: sessionmaker[Session]) -> V2StoredReportService:
    """Return the report service reading through ``sessions``."""
    return V2StoredReportService(
        StoredReportDatabaseSession(sessions),
        current_versions=lambda country_id: CURRENT_VERSIONS,
    )


@dataclass(frozen=True)
class ReportPlace:
    """Where a report calculates: its model, catalog version, dataset and region."""

    country: str
    model_id: UUID
    version_id: UUID
    dataset_id: UUID
    region_id: UUID


@dataclass(frozen=True)
class ReportToStore:
    """The report columns a test chooses; the rest are fixed.

    A report with a ``dataset_independent_key`` also gets a ``key_version``
    and a definition key of its own, as the simulation service stores them;
    without one it has no keys, as a report stored before them.
    """

    dataset_independent_key: str | None
    created_at: datetime = STORED_AT
    report_id: UUID | None = None
    budget_window_size: int | None = None


def store_economy_report(
    session: Session, place: ReportPlace, report: ReportToStore
) -> UUID:
    """Store an economy report, or a budget window, of current law against itself."""
    simulations = [
        Simulation(
            simulation_type=SimulationType.ECONOMY,
            dataset_id=place.dataset_id,
            region_id=place.region_id,
            tax_benefit_model_version_id=place.version_id,
            year=2026,
        )
        for _ in range(2)
    ]
    session.add_all(simulations)
    session.flush()
    keys = (
        {}
        if report.dataset_independent_key is None
        else {
            "key_version": 1,
            "definition_key": uuid4().hex * 2,
            "dataset_independent_key": report.dataset_independent_key,
        }
    )
    stored = Report(
        id=uuid4() if report.report_id is None else report.report_id,
        label="A stored report",
        country=place.country,
        tax_benefit_model_id=place.model_id,
        baseline_simulation_id=simulations[0].id,
        reform_simulation_id=simulations[1].id,
        dataset_id=place.dataset_id,
        region_id=place.region_id,
        year=2026,
        budget_window_size=report.budget_window_size,
        inputs={},
        created_at=report.created_at,
        **keys,
    )
    session.add(stored)
    session.commit()
    return stored.id
