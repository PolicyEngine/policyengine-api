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
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

from policyengine_api.data.v2.models import (
    Dataset,
    Region,
    RegionType,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from tests.unit.v2.sqlite_report_rows import (
    ReportPlace,
    ReportToStore,
    report_service,
    sqlite_sessions,
    store_economy_report,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

    from policyengine_api.services.v2.stored_reports.services import (
        V2StoredReportService,
    )

DATASET_INDEPENDENT_KEY = "bcabc98b4e0d3eff" * 4


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    yield from sqlite_sessions()


@pytest.fixture
def reports(sessions: sessionmaker[Session]) -> V2StoredReportService:
    return report_service(sessions)


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
    return store_economy_report(
        session,
        ReportPlace(
            country="uk",
            model_id=catalog.model_id,
            version_id=catalog.version_id,
            dataset_id=catalog.datasets[dataset_name],
            region_id=catalog.regions[region_code],
        ),
        ReportToStore(dataset_independent_key=DATASET_INDEPENDENT_KEY),
    )


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
    # A constituency's own report runs on the local-area dataset filtered to
    # that constituency, so it has no other areas to list.
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
