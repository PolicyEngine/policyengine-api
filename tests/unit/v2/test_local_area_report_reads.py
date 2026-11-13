"""Read which v2 reports are local-area reports, from their catalog rows.

The tables are SQLite's copy of the v2 schema. A report created with
``data_source: "local_area_dataset"`` is stored as an ordinary report on the
dataset the catalog version gives local areas, and nothing stores the
request's field. So a UK-wide or nation report is a local-area report when
its dataset is the default dataset of both the constituency and the
local-authority regions, as the simulation service decides it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine

from policyengine_api.data.v2.models import (
    V2_METADATA,
    Dataset,
    Region,
    RegionType,
    Report,
    Simulation,
    SimulationType,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.services.v2.simulation_service.types import PackageVersions
from policyengine_api.services.v2.stored_reports.database_session import (
    StoredReportDatabaseSession,
)
from policyengine_api.services.v2.stored_reports.services import V2StoredReportService

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine

STORED_AT = datetime(2026, 11, 14, 9, tzinfo=UTC)
DATASET_INDEPENDENT_KEY = "bcabc98b4e0d3eff" * 4


def current_versions(country_id: str) -> PackageVersions:
    return PackageVersions(
        country_package_version="2.1.0", policyengine_version="6.17.1"
    )


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
class UKCatalog:
    """A UK catalog version: its datasets and regions by code."""

    model_id: UUID
    version_id: UUID
    datasets: dict[str, UUID]
    regions: dict[str, UUID]


def store_uk_catalog(
    session: Session, *, local_authority_dataset: str = "microcosm_uk_2024_25_dense"
) -> UKCatalog:
    """Store a UK catalog version as .py 6.17.1's bundle describes it.

    UK-wide and the nations use the national dataset; constituencies use the
    local-area dataset, and local authorities ``local_authority_dataset``,
    the local-area dataset unless a test names another.
    """
    model = TaxBenefitModel(name="policyengine-uk")
    version = TaxBenefitModelVersion(
        model=model,
        version=f"local-areas-{uuid4().hex[:8]}",
        current_law_id=1,
        metadata_time_periods=[2026],
    )
    session.add_all([model, version])
    session.flush()
    datasets = {
        name: Dataset(name=name, year=2026, tax_benefit_model_version_id=version.id)
        for name in {
            "microcosm_uk_2024_25",
            "microcosm_uk_2024_25_dense",
            local_authority_dataset,
        }
    }
    session.add_all(datasets.values())
    session.flush()
    region_rows = [
        ("uk", RegionType.NATIONAL, "microcosm_uk_2024_25"),
        ("country/wales", RegionType.COUNTRY, "microcosm_uk_2024_25"),
        (
            "constituency/W07000081",
            RegionType.CONSTITUENCY,
            "microcosm_uk_2024_25_dense",
        ),
        (
            "local_authority/W06000015",
            RegionType.LOCAL_AUTHORITY,
            local_authority_dataset,
        ),
    ]
    regions = {
        code: Region(
            code=code,
            label=code,
            region_type=region_type,
            tax_benefit_model_version_id=version.id,
            default_dataset_id=datasets[dataset_name].id,
        )
        for code, region_type, dataset_name in region_rows
    }
    session.add_all(regions.values())
    session.commit()
    return UKCatalog(
        model_id=model.id,
        version_id=version.id,
        datasets={name: dataset.id for name, dataset in datasets.items()},
        regions={code: region.id for code, region in regions.items()},
    )


def store_report(
    session: Session, catalog: UKCatalog, *, region_code: str, dataset_name: str
) -> UUID:
    """Store a UK economy report of current law on the region and dataset named."""
    simulations = [
        Simulation(
            simulation_type=SimulationType.ECONOMY,
            dataset_id=catalog.datasets[dataset_name],
            region_id=catalog.regions[region_code],
            tax_benefit_model_version_id=catalog.version_id,
            year=2026,
        )
        for _ in range(2)
    ]
    session.add_all(simulations)
    session.flush()
    report = Report(
        label="A UK report",
        country="uk",
        tax_benefit_model_id=catalog.model_id,
        baseline_simulation_id=simulations[0].id,
        reform_simulation_id=simulations[1].id,
        dataset_id=catalog.datasets[dataset_name],
        region_id=catalog.regions[region_code],
        year=2026,
        inputs={},
        created_at=STORED_AT,
        key_version=1,
        definition_key=uuid4().hex * 2,
        dataset_independent_key=DATASET_INDEPENDENT_KEY,
    )
    session.add(report)
    session.commit()
    return report.id


@pytest.mark.parametrize("region_code", ["uk", "country/wales"], ids=["uk", "nation"])
def test_a_uk_wide_or_nation_report_on_the_local_area_dataset_is_a_local_area_report(
    sessions: sessionmaker[Session], reports: V2StoredReportService, region_code: str
) -> None:
    with sessions() as session:
        catalog = store_uk_catalog(session)
        report_id = store_report(
            session,
            catalog,
            region_code=region_code,
            dataset_name="microcosm_uk_2024_25_dense",
        )

    read = reports.get_report(country_id="uk", report_id=report_id)
    (listed,) = reports.list_reports(country_id="uk", report_ids=[report_id])
    (found,) = reports.search_reports(
        country_id="uk", dataset_independent_key=DATASET_INDEPENDENT_KEY
    )

    assert read.data_source == "local_area_dataset"
    assert read.dataset_name == "microcosm_uk_2024_25_dense"
    assert listed.data_source == "local_area_dataset"
    assert found.data_source == "local_area_dataset"


@pytest.mark.parametrize("region_code", ["uk", "country/wales"], ids=["uk", "nation"])
def test_a_report_on_its_regions_own_dataset_is_not_a_local_area_report(
    sessions: sessionmaker[Session], reports: V2StoredReportService, region_code: str
) -> None:
    with sessions() as session:
        report_id = store_report(
            session,
            store_uk_catalog(session),
            region_code=region_code,
            dataset_name="microcosm_uk_2024_25",
        )

    read = reports.get_report(country_id="uk", report_id=report_id)

    assert read.data_source is None


def test_a_local_area_regions_own_report_is_not_a_local_area_report(
    sessions: sessionmaker[Session], reports: V2StoredReportService
) -> None:
    # A constituency's report calculates its one area on the national run.
    with sessions() as session:
        report_id = store_report(
            session,
            store_uk_catalog(session),
            region_code="constituency/W07000081",
            dataset_name="microcosm_uk_2024_25_dense",
        )

    read = reports.get_report(country_id="uk", report_id=report_id)

    assert read.data_source is None


def test_a_dataset_only_one_level_of_area_uses_is_not_the_local_area_dataset(
    sessions: sessionmaker[Session], reports: V2StoredReportService
) -> None:
    # A release whose two area levels name different datasets doesn't route
    # areas to their own dataset, so it has no local-area dataset.
    with sessions() as session:
        report_id = store_report(
            session,
            store_uk_catalog(session, local_authority_dataset="microcosm_uk_la_only"),
            region_code="uk",
            dataset_name="microcosm_uk_2024_25_dense",
        )

    read = reports.get_report(country_id="uk", report_id=report_id)

    assert read.data_source is None
