"""Read v2 reports' dataset-independent keys, and find reports by one.

The tables are SQLite's copy of the v2 schema. The simulation service stores
each report's ``dataset_independent_key``: its definition without the
dataset, which a national report shares with its local-area report. Reports
created before the keys have none.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine

from policyengine_api.data.v2.models import (
    V2_METADATA,
    Dataset,
    Household,
    Region,
    RegionType,
    Report,
    Simulation,
    SimulationType,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.query_parameters import MAXIMUM_LISTED_REPORTS
from policyengine_api.services.v2.simulation_service.types import PackageVersions
from policyengine_api.services.v2.stored_reports.database_session import (
    StoredReportDatabaseSession,
)
from policyengine_api.services.v2.stored_reports.services import V2StoredReportService

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine

STORED_AT = datetime(2026, 11, 14, 9, tzinfo=UTC)
CURRENT_VERSIONS = PackageVersions(
    country_package_version="2.1.0", policyengine_version="6.17.1"
)
# The shared key of the proposal's worked example, and another report's.
DATASET_INDEPENDENT_KEY = "bcabc98b4e0d3eff" * 4
OTHER_DATASET_INDEPENDENT_KEY = "4bb1299756cb0a89" * 4


def current_versions(country_id: str) -> PackageVersions:
    return CURRENT_VERSIONS


@pytest.fixture
def engine() -> Iterator[Engine]:
    database_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    V2_METADATA.create_all(database_engine)
    yield database_engine
    database_engine.dispose()


@pytest.fixture
def sessions(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, class_=Session, expire_on_commit=False)


@pytest.fixture
def reports(sessions: sessionmaker[Session]) -> V2StoredReportService:
    return V2StoredReportService(
        StoredReportDatabaseSession(sessions), current_versions=current_versions
    )


@dataclass(frozen=True)
class StoredCatalog:
    """A country's model, a catalog version of it, its national dataset and region."""

    country: str
    model_id: UUID
    version_id: UUID
    dataset_id: UUID
    region_id: UUID


def store_catalog(session: Session, country: str) -> StoredCatalog:
    """Store a catalog version of the country's model with its national region."""
    model = TaxBenefitModel(name=f"policyengine-{country}")
    version = TaxBenefitModelVersion(
        model=model,
        version=f"keys-{uuid4().hex[:8]}",
        current_law_id=1,
        metadata_time_periods=[2026],
    )
    dataset = Dataset(
        name=f"national_{country}_2026",
        year=2026,
        tax_benefit_model_version=version,
    )
    session.add_all([model, version, dataset])
    session.flush()
    region = Region(
        code=country,
        label=country.upper(),
        region_type=RegionType.NATIONAL,
        tax_benefit_model_version_id=version.id,
        default_dataset_id=dataset.id,
    )
    session.add(region)
    session.commit()
    return StoredCatalog(
        country=country,
        model_id=model.id,
        version_id=version.id,
        dataset_id=dataset.id,
        region_id=region.id,
    )


def _keys(dataset_independent_key: str | None) -> dict[str, object]:
    """Return a report's key columns: all three, or none for an unkeyed report."""
    if dataset_independent_key is None:
        return {}
    return {
        "key_version": 1,
        "definition_key": uuid4().hex * 2,
        "dataset_independent_key": dataset_independent_key,
    }


def store_report(  # noqa: PLR0913  # the catalog, then each column a test varies
    session: Session,
    catalog: StoredCatalog,
    *,
    dataset_independent_key: str | None,
    created_at: datetime = STORED_AT,
    report_id: UUID | None = None,
    budget_window_size: int | None = None,
) -> UUID:
    """Store an economy report or budget window of current law against itself."""
    simulations = [
        Simulation(
            simulation_type=SimulationType.ECONOMY,
            dataset_id=catalog.dataset_id,
            region_id=catalog.region_id,
            tax_benefit_model_version_id=catalog.version_id,
            year=2026,
        )
        for _ in range(2)
    ]
    session.add_all(simulations)
    session.flush()
    report = Report(
        id=uuid4() if report_id is None else report_id,
        label="A stored report",
        country=catalog.country,
        tax_benefit_model_id=catalog.model_id,
        baseline_simulation_id=simulations[0].id,
        reform_simulation_id=simulations[1].id,
        dataset_id=catalog.dataset_id,
        region_id=catalog.region_id,
        year=2026,
        budget_window_size=budget_window_size,
        inputs={},
        created_at=created_at,
        **_keys(dataset_independent_key),
    )
    session.add(report)
    session.commit()
    return report.id


def store_household_report(
    session: Session, catalog: StoredCatalog, *, dataset_independent_key: str
) -> UUID:
    """Store a household report of current law against itself."""
    household = Household(
        country_id=catalog.country,
        default_year=2026,
        household_data={"people": {"you": {"age": {"2026": 40}}}},
        canonicalization_version=1,
        content_hash=uuid4().hex * 2,
    )
    session.add(household)
    session.flush()
    simulations = [
        Simulation(
            simulation_type=SimulationType.HOUSEHOLD,
            household_id=household.id,
            tax_benefit_model_version_id=catalog.version_id,
            year=2026,
        )
        for _ in range(2)
    ]
    session.add_all(simulations)
    session.flush()
    report = Report(
        label="My household",
        country=catalog.country,
        tax_benefit_model_id=catalog.model_id,
        baseline_simulation_id=simulations[0].id,
        reform_simulation_id=simulations[1].id,
        household_id=household.id,
        year=2026,
        inputs={},
        created_at=STORED_AT,
        **_keys(dataset_independent_key),
    )
    session.add(report)
    session.commit()
    return report.id


def test_every_kind_of_report_read_answers_its_dataset_independent_key(
    sessions: sessionmaker[Session], reports: V2StoredReportService
) -> None:
    with sessions() as session:
        catalog = store_catalog(session, "uk")
        economy_id = store_report(
            session, catalog, dataset_independent_key=DATASET_INDEPENDENT_KEY
        )
        window_id = store_report(
            session,
            catalog,
            dataset_independent_key=OTHER_DATASET_INDEPENDENT_KEY,
            budget_window_size=3,
        )
        household_id = store_household_report(
            session, catalog, dataset_independent_key=DATASET_INDEPENDENT_KEY
        )

    reads = {
        report_id: reports.get_report(country_id="uk", report_id=report_id)
        for report_id in (economy_id, window_id, household_id)
    }
    listed = reports.list_reports(
        country_id="uk", report_ids=[economy_id, window_id, household_id]
    )

    assert {
        report_id: read.dataset_independent_key for report_id, read in reads.items()
    } == {
        economy_id: DATASET_INDEPENDENT_KEY,
        window_id: OTHER_DATASET_INDEPENDENT_KEY,
        household_id: DATASET_INDEPENDENT_KEY,
    }
    assert [(item.kind, item.dataset_independent_key) for item in listed] == [
        ("economy", DATASET_INDEPENDENT_KEY),
        ("budget_window", OTHER_DATASET_INDEPENDENT_KEY),
        ("household", DATASET_INDEPENDENT_KEY),
    ]


def test_a_report_created_before_the_keys_reads_no_dataset_independent_key(
    sessions: sessionmaker[Session], reports: V2StoredReportService
) -> None:
    with sessions() as session:
        report_id = store_report(
            session, store_catalog(session, "uk"), dataset_independent_key=None
        )

    read = reports.get_report(country_id="uk", report_id=report_id)

    assert read.dataset_independent_key is None


def test_a_search_finds_the_countrys_reports_with_the_key_newest_first(
    sessions: sessionmaker[Session], reports: V2StoredReportService
) -> None:
    with sessions() as session:
        uk = store_catalog(session, "uk")
        us = store_catalog(session, "us")
        oldest, newest, middle = (
            store_report(
                session,
                uk,
                dataset_independent_key=DATASET_INDEPENDENT_KEY,
                created_at=STORED_AT + timedelta(minutes=minutes),
            )
            for minutes in (0, 20, 10)
        )
        store_report(session, uk, dataset_independent_key=OTHER_DATASET_INDEPENDENT_KEY)
        store_report(session, uk, dataset_independent_key=None)
        store_report(session, us, dataset_independent_key=DATASET_INDEPENDENT_KEY)

    found = reports.search_reports(
        country_id="uk", dataset_independent_key=DATASET_INDEPENDENT_KEY
    )

    assert [read.id for read in found] == [newest, middle, oldest]
    assert all(
        read.dataset_independent_key == DATASET_INDEPENDENT_KEY for read in found
    )
    assert all(not hasattr(read, "result") for read in found)


def test_a_search_puts_the_larger_id_first_among_reports_created_together(
    sessions: sessionmaker[Session], reports: V2StoredReportService
) -> None:
    smaller_id = UUID("00000000-0000-4000-8000-000000000001")
    larger_id = UUID("ffffffff-0000-4000-8000-000000000001")
    with sessions() as session:
        catalog = store_catalog(session, "uk")
        for report_id in (smaller_id, larger_id):
            store_report(
                session,
                catalog,
                dataset_independent_key=DATASET_INDEPENDENT_KEY,
                report_id=report_id,
            )

    found = reports.search_reports(
        country_id="uk", dataset_independent_key=DATASET_INDEPENDENT_KEY
    )

    assert [read.id for read in found] == [larger_id, smaller_id]


def test_a_search_answers_at_most_the_newest_twenty_five_reports(
    sessions: sessionmaker[Session], reports: V2StoredReportService
) -> None:
    with sessions() as session:
        catalog = store_catalog(session, "uk")
        stored = [
            store_report(
                session,
                catalog,
                dataset_independent_key=DATASET_INDEPENDENT_KEY,
                created_at=STORED_AT + timedelta(minutes=minutes),
            )
            for minutes in range(MAXIMUM_LISTED_REPORTS + 1)
        ]

    found = reports.search_reports(
        country_id="uk", dataset_independent_key=DATASET_INDEPENDENT_KEY
    )

    assert [read.id for read in found] == stored[:0:-1]


def test_a_search_with_a_key_no_report_has_finds_none(
    sessions: sessionmaker[Session], reports: V2StoredReportService
) -> None:
    with sessions() as session:
        store_report(
            session,
            store_catalog(session, "uk"),
            dataset_independent_key=DATASET_INDEPENDENT_KEY,
        )

    found = reports.search_reports(
        country_id="uk", dataset_independent_key=OTHER_DATASET_INDEPENDENT_KEY
    )

    assert found == ()
