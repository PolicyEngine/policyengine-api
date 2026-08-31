"""Disposable-Postgres coverage for Stage 9 catalog publication."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import NullPool
from sqlmodel import Session, select

from policyengine_api.data.v2.catalog.publication import (
    CatalogPublicationError,
    publish_catalog,
)
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL
from policyengine_api.data.v2.models import (
    Dataset,
    DatasetVersion,
    Region,
    Report,
    ReportRun,
    Simulation,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from tests.fixtures.v2_catalog import normalized_catalog


REPO = Path(__file__).parents[2]
DISPOSABLE_DATABASE = "policyengine_v2_alembic_test"


def _disposable_url() -> str:
    database_url = os.environ.get(V2_MIGRATION_DATABASE_URL, "")
    if not database_url:
        pytest.skip(f"{V2_MIGRATION_DATABASE_URL} is not set")
    url = make_url(database_url)
    if url.database != DISPOSABLE_DATABASE or url.host not in {
        "localhost",
        "127.0.0.1",
        "::1",
        "postgres",
    }:
        pytest.fail("catalog publication tests require disposable local Postgres")
    return database_url


@pytest.fixture
def publication_engine() -> Engine:
    database_url = _disposable_url()
    config = Config(str(REPO / "alembic-v2.ini"))
    command.upgrade(config, "head")
    engine = create_engine(database_url, poolclass=NullPool)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE tax_benefit_models CASCADE"))
    yield engine
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE tax_benefit_models CASCADE"))
    engine.dispose()


def _counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table_name: connection.execute(
                text(f"SELECT count(*) FROM {table_name}")
            ).scalar_one()
            for table_name in (
                "tax_benefit_models",
                "tax_benefit_model_versions",
                "variables",
                "parameter_nodes",
                "parameters",
                "parameter_values",
                "datasets",
                "dataset_versions",
                "regions",
                "simulations",
                "reports",
                "report_runs",
            )
        }


def _identifiers(engine: Engine) -> dict[str, tuple[str, ...]]:
    with engine.connect() as connection:
        return {
            table_name: tuple(
                str(value)
                for value in connection.execute(
                    text(f"SELECT id FROM {table_name} ORDER BY id")
                ).scalars()
            )
            for table_name in (
                "tax_benefit_models",
                "tax_benefit_model_versions",
                "variables",
                "parameter_nodes",
                "parameters",
                "parameter_values",
                "datasets",
                "regions",
            )
        }


def test_publish_and_republish_preserve_complete_catalog(
    publication_engine: Engine,
) -> None:
    catalog = normalized_catalog()

    first = publish_catalog(publication_engine, catalog)
    first_counts = _counts(publication_engine)
    first_ids = _identifiers(publication_engine)
    second = publish_catalog(publication_engine, catalog)

    assert first.as_dict()["outcome"] == "ok"
    assert second.policyengine_version == first.policyengine_version
    assert (
        _counts(publication_engine)
        == first_counts
        == {
            "tax_benefit_models": 2,
            "tax_benefit_model_versions": 2,
            "variables": 2,
            "parameter_nodes": 2,
            "parameters": 2,
            "parameter_values": 4,
            "datasets": 3,
            "dataset_versions": 0,
            "regions": 5,
            "simulations": 0,
            "reports": 0,
            "report_runs": 0,
        }
    )
    assert _identifiers(publication_engine) == first_ids

    with publication_engine.connect() as connection:
        datasets = connection.execute(
            text(
                "SELECT name, storage_path, is_output_dataset "
                "FROM datasets ORDER BY name"
            )
        ).all()
        region_defaults = connection.execute(
            text(
                """
                SELECT region.code, dataset.name
                FROM regions AS region
                JOIN datasets AS dataset ON dataset.id = region.default_dataset_id
                ORDER BY region.code
                """
            )
        ).all()
    assert all(
        storage_path is None and not output for _, storage_path, output in datasets
    )
    assert dict(region_defaults) == {
        "country/england": "enhanced_frs_2024_25",
        "place/CA-44000": "populace_us_2024",
        "state/ca": "populace_us_ca_2024",
        "uk": "enhanced_frs_2024_25",
        "us": "populace_us_2024",
    }


@pytest.mark.parametrize(
    "failure_point",
    ["during_copy", "after_reconciliation", "after_validation"],
)
def test_failure_during_publication_rolls_back_every_catalog_write(
    publication_engine: Engine,
    failure_point: str,
) -> None:
    def fail(point: str, _connection) -> None:
        if point == failure_point:
            raise RuntimeError("injected failure")

    with pytest.raises(RuntimeError, match="injected failure"):
        publish_catalog(
            publication_engine,
            normalized_catalog(),
            checkpoint=fail,
        )

    assert all(count == 0 for count in _counts(publication_engine).values())


def test_same_version_with_changed_content_fails_without_mutation(
    publication_engine: Engine,
) -> None:
    catalog = normalized_catalog()
    publish_catalog(publication_engine, catalog)
    before_ids = _identifiers(publication_engine)
    before_counts = _counts(publication_engine)
    us = catalog.country("us")
    changed_variable = replace(us.variables[0], label="Changed label")
    changed_us = replace(us, variables=(changed_variable,))
    changed = replace(
        catalog,
        countries=(changed_us, catalog.country("uk")),
    )

    with pytest.raises(CatalogPublicationError, match="differs"):
        publish_catalog(publication_engine, changed)

    assert _identifiers(publication_engine) == before_ids
    assert _counts(publication_engine) == before_counts


def test_republish_preserves_existing_run_and_dataset_version_records(
    publication_engine: Engine,
) -> None:
    catalog = normalized_catalog()
    publish_catalog(publication_engine, catalog)

    with Session(publication_engine) as session:
        model = session.exec(
            select(TaxBenefitModel).where(TaxBenefitModel.name == "policyengine-us")
        ).one()
        model_version = session.exec(
            select(TaxBenefitModelVersion).where(
                TaxBenefitModelVersion.model_id == model.id
            )
        ).one()
        input_dataset = session.exec(
            select(Dataset).where(
                Dataset.tax_benefit_model_version_id == model_version.id,
                Dataset.name == "populace_us_2024",
            )
        ).one()
        region = session.exec(
            select(Region).where(
                Region.tax_benefit_model_version_id == model_version.id,
                Region.code == "us",
            )
        ).one()
        output_dataset = Dataset(
            name="existing-run-output",
            description="Existing generated output",
            storage_path="private-output-reference",
            year=2025,
            is_output_dataset=True,
            tax_benefit_model_version_id=model_version.id,
        )
        session.add(output_dataset)
        session.flush()
        dataset_version = DatasetVersion(
            name="existing-user-version",
            description="Existing independently versioned data",
            dataset_id=output_dataset.id,
            tax_benefit_model_id=model.id,
        )
        simulation = Simulation(
            dataset_id=input_dataset.id,
            output_dataset_id=output_dataset.id,
            tax_benefit_model_version_id=model_version.id,
            region_id=region.id,
        )
        report = Report(
            label="Existing report",
            country="us",
            tax_benefit_model_id=model.id,
            dataset_id=input_dataset.id,
            region_id=region.id,
        )
        session.add_all((dataset_version, simulation, report))
        session.flush()
        report_run = ReportRun(
            report_id=report.id,
            country_package_version="existing-country-version",
            policyengine_version="existing-policyengine-version",
        )
        session.add(report_run)
        session.commit()
        protected_ids = (
            dataset_version.id,
            simulation.id,
            report.id,
            report_run.id,
            simulation.dataset_id,
            simulation.output_dataset_id,
            report.dataset_id,
        )

    publish_catalog(publication_engine, catalog)

    with Session(publication_engine) as session:
        persisted_dataset_version = session.get(DatasetVersion, protected_ids[0])
        persisted_simulation = session.get(Simulation, protected_ids[1])
        persisted_report = session.get(Report, protected_ids[2])
        persisted_report_run = session.get(ReportRun, protected_ids[3])
        assert persisted_dataset_version is not None
        assert persisted_simulation is not None
        assert persisted_report is not None
        assert persisted_report_run is not None
        assert persisted_simulation.dataset_id == protected_ids[4]
        assert persisted_simulation.output_dataset_id == protected_ids[5]
        assert persisted_report.dataset_id == protected_ids[6]


def test_new_version_is_additive_and_concurrent_retries_serialize(
    publication_engine: Engine,
) -> None:
    first = normalized_catalog()
    newer = normalized_catalog(policyengine_version="4.21.0")
    publish_catalog(publication_engine, first)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _index: publish_catalog(publication_engine, newer),
                range(2),
            )
        )

    assert [result.policyengine_version for result in results] == [
        "4.21.0",
        "4.21.0",
    ]
    assert _counts(publication_engine) == {
        "tax_benefit_models": 2,
        "tax_benefit_model_versions": 4,
        "variables": 4,
        "parameter_nodes": 4,
        "parameters": 4,
        "parameter_values": 8,
        "datasets": 6,
        "dataset_versions": 0,
        "regions": 10,
        "simulations": 0,
        "reports": 0,
        "report_runs": 0,
    }
