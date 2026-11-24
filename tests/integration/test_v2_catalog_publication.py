"""Disposable-Postgres coverage for Stage 9 catalog publication."""

from __future__ import annotations

import gzip
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlmodel import col, select

from policyengine_api.data.v2.catalog import publication as publication_module
from policyengine_api.data.v2.catalog.extraction import extract_catalog
from policyengine_api.data.v2.catalog.publication import (
    CatalogPublicationError,
    publish_catalog,
    unpublished_countries,
)
from policyengine_api.data.v2.catalog.records import EnumValueRecord
from policyengine_api.data.v2.models import (
    Dataset,
    DatasetVersion,
    Parameter,
    ParameterNode,
    ParameterSearchFile,
    ParameterTreeChild,
    ParameterValue,
    Region,
    Report,
    ReportRun,
    Simulation,
    SimulationRun,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    Variable,
)
from policyengine_api.data.v2.privileges import CATALOG_WRITER_ROLE
from tests.fixtures import database_sessions
from tests.fixtures.v2_catalog import (
    POLICYENGINE_VERSION,
    add_format_2_variable_records,
    bundle,
    installed_version,
    normalized_catalog,
    region_references,
    source_models,
)
from tests.fixtures.v2_catalog_value_shapes import (
    PARAMETER_CASES,
    REGION_FILTER_VALUES,
    value_shape_catalog,
)
from tests.integration.catalog_publication_support import (
    clear_format_2_fields,
    emptied_catalog,
    row_counts,
    stored_identifiers,
)
from tests.integration.catalog_rows import (
    CATALOG_COLUMNS,
    assert_catalog_stored_unchanged,
    stored_catalog_rows,
    stored_parameter_values,
    strict_json,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

# The tables whose rows the tests count: the catalog's, and those that name it.
COUNTED_MODELS: dict[str, Any] = {
    "tax_benefit_models": TaxBenefitModel,
    "tax_benefit_model_versions": TaxBenefitModelVersion,
    "variables": Variable,
    "parameter_nodes": ParameterNode,
    "parameters": Parameter,
    "parameter_values": ParameterValue,
    "datasets": Dataset,
    "dataset_versions": DatasetVersion,
    "regions": Region,
    "simulations": Simulation,
    "reports": Report,
    "report_runs": ReportRun,
}


@pytest.fixture
def publication_sessions(
    v2_owner_sessions: sessionmaker[Session],
) -> Iterator[sessionmaker[Session]]:
    with emptied_catalog(v2_owner_sessions) as sessions:
        yield sessions


def _counts(sessions: sessionmaker[Session]) -> dict[str, int]:
    return row_counts(sessions, COUNTED_MODELS)


def _identifiers(sessions: sessionmaker[Session]) -> dict[str, tuple[str, ...]]:
    return stored_identifiers(sessions)


def _us_version_id() -> sa.ScalarSelect[Any]:
    """Select the ID of the US model's stored version, of which there is one."""
    return (
        select(col(TaxBenefitModelVersion.id))
        .join(
            TaxBenefitModel,
            col(TaxBenefitModel.id) == col(TaxBenefitModelVersion.model_id),
        )
        .where(col(TaxBenefitModel.name) == "policyengine-us")
        .scalar_subquery()
    )


def _version_ids(version: str) -> sa.Select[Any]:
    """Select the IDs of the stored versions of one .py version, for every model."""
    return select(col(TaxBenefitModelVersion.id)).where(
        col(TaxBenefitModelVersion.version) == version
    )


def test_publish_and_republish_preserve_complete_catalog(
    publication_sessions: sessionmaker[Session],
) -> None:
    catalog = normalized_catalog()

    first = publish_catalog(publication_sessions, catalog)
    first_counts = _counts(publication_sessions)
    first_ids = _identifiers(publication_sessions)
    second = publish_catalog(publication_sessions, catalog)

    assert first.as_dict()["outcome"] == "ok"
    assert first.omitted_region_summaries == (("us", "place", 1),)
    assert second.policyengine_version == first.policyengine_version
    assert (
        _counts(publication_sessions)
        == first_counts
        == {
            "tax_benefit_models": 2,
            "tax_benefit_model_versions": 2,
            "variables": 2,
            "parameter_nodes": 2,
            "parameters": 2,
            "parameter_values": 4,
            "datasets": 4,
            "dataset_versions": 0,
            "regions": 8,
            "simulations": 0,
            "reports": 0,
            "report_runs": 0,
        }
    )
    assert _identifiers(publication_sessions) == first_ids

    with publication_sessions() as session:
        datasets = session.execute(
            select(
                col(Dataset.name),
                col(Dataset.storage_path),
                col(Dataset.is_output_dataset),
            ).order_by(col(Dataset.name))
        ).all()
        region_defaults = session.execute(
            select(col(Region.code), col(Dataset.name))
            .join(Dataset, col(Dataset.id) == col(Region.default_dataset_id))
            .order_by(col(Region.code))
        ).all()
    assert all(
        storage_path is None and not output for _, storage_path, output in datasets
    )
    assert dict(region_defaults) == {
        "congressional_district/CA-01": "populace_us_2024_acs_local",
        "constituency/E14001063": "microcosm_uk_2024_25_dense",
        "country/england": "microcosm_uk_2024_25",
        "country/northern_ireland": "microcosm_uk_2024_25",
        "local_authority/N09000011": "microcosm_uk_2024_25_dense",
        "state/ca": "populace_us_2024_acs_local",
        "uk": "microcosm_uk_2024_25",
        "us": "populace_us_2024",
    }


def test_unpublished_country_check_reports_a_missing_schema_specifically(
    disposable_v2_database_url: str,
) -> None:
    # The same server's maintenance database has no v2 schema at all.
    schema_less = make_url(disposable_v2_database_url).set(database="postgres")
    with (
        database_sessions.v2_owner_sessions(
            schema_less.render_as_string(hide_password=False)
        ) as schema_less_sessions,
        pytest.raises(
            CatalogPublicationError,
            match=r"^the v2 Alembic revision table is absent$",
        ),
    ):
        unpublished_countries(schema_less_sessions, normalized_catalog())


def test_lists_only_countries_whose_catalog_version_is_not_stored(
    publication_sessions: sessionmaker[Session],
) -> None:
    catalog = normalized_catalog()
    newer = normalized_catalog(policyengine_version="4.21.0")

    assert unpublished_countries(publication_sessions, catalog) == ("us", "uk")
    publish_catalog(publication_sessions, catalog)

    assert unpublished_countries(publication_sessions, catalog) == ()
    assert unpublished_countries(publication_sessions, newer) == ("us", "uk")


@pytest.mark.parametrize(
    "failure_point",
    ["during_copy", "after_reconciliation", "after_validation"],
)
def test_failure_during_publication_rolls_back_every_catalog_write(
    publication_sessions: sessionmaker[Session],
    failure_point: str,
) -> None:
    def fail(point: str, _session) -> None:
        if point == failure_point:
            msg = "injected failure"
            raise RuntimeError(msg)

    with pytest.raises(RuntimeError, match="injected failure"):
        publish_catalog(
            publication_sessions,
            normalized_catalog(),
            checkpoint=fail,
        )

    assert all(count == 0 for count in _counts(publication_sessions).values())


def test_same_version_with_changed_content_fails_without_mutation(
    publication_sessions: sessionmaker[Session],
) -> None:
    catalog = normalized_catalog()
    publish_catalog(publication_sessions, catalog)
    before_ids = _identifiers(publication_sessions)
    before_counts = _counts(publication_sessions)
    us = catalog.country("us")
    changed_variable = replace(us.variables[0], label="Changed label")
    changed_us = replace(us, variables=(changed_variable,))
    changed = replace(
        catalog,
        countries=(changed_us, catalog.country("uk")),
    )

    with pytest.raises(
        CatalogPublicationError,
        match=r"^the stored us catalog version 5\.0\.4 differs from the staged "
        r"catalog in its variables$",
    ):
        publish_catalog(publication_sessions, changed)

    assert _identifiers(publication_sessions) == before_ids
    assert _counts(publication_sessions) == before_counts


def test_stored_version_with_a_different_dataset_names_the_datasets(
    publication_sessions: sessionmaker[Session],
) -> None:
    catalog = normalized_catalog()
    publish_catalog(publication_sessions, catalog)
    uk = catalog.country("uk")
    changed = replace(
        catalog,
        countries=(
            catalog.country("us"),
            replace(
                uk,
                datasets=tuple(
                    replace(dataset, description="Another dataset selection")
                    for dataset in uk.datasets
                ),
            ),
        ),
    )

    with pytest.raises(
        CatalogPublicationError,
        match=r"^the stored uk catalog version 5\.0\.4 differs from the staged "
        r"catalog in its datasets$",
    ):
        publish_catalog(publication_sessions, changed)


def _region_rows(sessions: sessionmaker[Session]) -> list[tuple[object, ...]]:
    with sessions() as session:
        return [
            tuple(row)
            for row in session.execute(
                sa.select(
                    col(Region.id),
                    col(Region.code),
                    col(Region.label),
                    col(Region.region_type),
                    col(Region.requires_filter),
                    col(Region.filter_field),
                    col(Region.filter_value),
                    col(Region.filter_strategy),
                    col(Region.parent_code),
                    col(Region.state_code),
                    col(Region.state_name),
                    col(Region.default_dataset_id),
                ).order_by(col(Region.id))
            )
        ]


def _with_changed_us_regions(catalog):
    """Relabel state/ca and drop the district, as a reference-file change would."""
    us = catalog.country("us")
    regions = tuple(
        replace(region, label="Changed California")
        if region.code == "state/ca"
        else region
        for region in us.regions
        if region.code != "congressional_district/CA-01"
    )
    return replace(
        catalog,
        countries=(replace(us, regions=regions), catalog.country("uk")),
    )


def test_stored_version_keeps_its_published_regions_and_logs_the_difference(
    publication_sessions: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = normalized_catalog()
    publish_catalog(publication_sessions, catalog)
    before_regions = _region_rows(publication_sessions)
    before_ids = _identifiers(publication_sessions)
    before_counts = _counts(publication_sessions)
    # Alembic's logging configuration disables existing loggers, so the
    # warnings are recorded where they are emitted.
    warnings: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        publication_module.LOGGER,
        "warning",
        lambda message, *args, **kwargs: warnings.append((message % args, kwargs)),
    )

    evidence = publish_catalog(publication_sessions, _with_changed_us_regions(catalog))

    assert evidence.as_dict()["outcome"] == "ok"
    assert _region_rows(publication_sessions) == before_regions
    assert _identifiers(publication_sessions) == before_ids
    assert _counts(publication_sessions) == before_counts
    # The evidence describes the stored rows, not the staged regions.
    assert evidence.entity_counts == {
        "models": before_counts["tax_benefit_models"],
        "model_versions": before_counts["tax_benefit_model_versions"],
        "variables": before_counts["variables"],
        "parameter_nodes": before_counts["parameter_nodes"],
        "parameters": before_counts["parameters"],
        "parameter_values": before_counts["parameter_values"],
        "datasets": before_counts["datasets"],
        "regions": before_counts["regions"],
    }
    assert evidence.kept_region_summaries == (
        ("us", catalog.policyengine_version, 3, 2),
    )
    assert evidence.omitted_region_summaries == ()
    assert evidence.fallback_summaries == ()
    notices = [
        (message, keywords["extra"])
        for message, keywords in warnings
        if message.startswith("kept the published regions")
    ]
    assert [message for message, _extra in notices] == [
        "kept the published regions of the stored us catalog version "
        f"{catalog.policyengine_version}: 1 staged region rows are not stored and "
        "2 stored region rows are not staged"
    ]
    assert [extra["policyengine_attributes"] for _message, extra in notices] == [
        {
            "country_id": "us",
            "policyengine_version": catalog.policyengine_version,
            "staged_region_rows_not_stored": 1,
            "stored_region_rows_not_staged": 2,
        }
    ]


def test_stored_version_with_changed_regions_still_fails_on_other_tables(
    publication_sessions: sessionmaker[Session],
) -> None:
    catalog = normalized_catalog()
    publish_catalog(publication_sessions, catalog)
    before_regions = _region_rows(publication_sessions)
    changed = _with_changed_us_regions(catalog)
    us = changed.country("us")
    changed = replace(
        changed,
        countries=(
            replace(us, variables=(replace(us.variables[0], label="Changed"),)),
            changed.country("uk"),
        ),
    )

    with pytest.raises(CatalogPublicationError, match="differs"):
        publish_catalog(publication_sessions, changed)

    assert _region_rows(publication_sessions) == before_regions


def test_new_version_publishes_the_reference_file_regions(
    publication_sessions: sessionmaker[Session],
) -> None:
    publish_catalog(publication_sessions, normalized_catalog())
    newer = _with_changed_us_regions(normalized_catalog(policyengine_version="4.21.0"))

    publish_catalog(publication_sessions, newer)

    with publication_sessions() as session:
        newer_us_regions = dict(
            session.execute(
                select(col(Region.code), col(Region.label))
                .join(
                    TaxBenefitModelVersion,
                    col(TaxBenefitModelVersion.id)
                    == col(Region.tax_benefit_model_version_id),
                )
                .join(
                    TaxBenefitModel,
                    col(TaxBenefitModel.id) == col(TaxBenefitModelVersion.model_id),
                )
                .where(
                    col(TaxBenefitModelVersion.version) == "4.21.0",
                    col(TaxBenefitModel.name) == "policyengine-us",
                )
            ).all()
        )
    assert newer_us_regions == {
        "state/ca": "Changed California",
        "us": "United States",
    }


def test_republish_preserves_existing_run_and_dataset_version_records(
    publication_sessions: sessionmaker[Session],
) -> None:
    catalog = normalized_catalog()
    publish_catalog(publication_sessions, catalog)

    with publication_sessions() as session:
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
        simulation_run = SimulationRun(
            simulation_id=simulation.id,
            year=2025,
            tax_benefit_model_version_id=model_version.id,
            country_package_version="existing-country-version",
            policyengine_version="existing-policyengine-version",
        )
        session.add(simulation_run)
        session.flush()
        report_run = ReportRun(
            report_id=report.id,
            baseline_simulation_run_id=simulation_run.id,
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
            report.dataset_id,
            dataset_version.dataset_id,
        )

    publish_catalog(publication_sessions, catalog)

    with publication_sessions() as session:
        persisted_dataset_version = session.get(DatasetVersion, protected_ids[0])
        persisted_simulation = session.get(Simulation, protected_ids[1])
        persisted_report = session.get(Report, protected_ids[2])
        persisted_report_run = session.get(ReportRun, protected_ids[3])
        assert persisted_dataset_version is not None
        assert persisted_simulation is not None
        assert persisted_report is not None
        assert persisted_report_run is not None
        assert persisted_simulation.dataset_id == protected_ids[4]
        assert persisted_report.dataset_id == protected_ids[5]
        assert persisted_dataset_version.dataset_id == protected_ids[6]
        # Republishing keeps every catalog row the simulation and report name.
        for dataset_id in (
            persisted_simulation.dataset_id,
            persisted_report.dataset_id,
        ):
            assert session.get(Dataset, dataset_id) is not None
        for region_id in (persisted_simulation.region_id, persisted_report.region_id):
            assert session.get(Region, region_id) is not None
        assert (
            session.get(
                TaxBenefitModelVersion,
                persisted_simulation.tax_benefit_model_version_id,
            )
            is not None
        )


def test_new_version_is_additive_and_concurrent_retries_serialize(
    publication_sessions: sessionmaker[Session],
) -> None:
    first = normalized_catalog()
    newer = normalized_catalog(policyengine_version="4.21.0")
    publish_catalog(publication_sessions, first)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _index: publish_catalog(publication_sessions, newer),
                range(2),
            )
        )

    assert [result.policyengine_version for result in results] == [
        "4.21.0",
        "4.21.0",
    ]
    assert _counts(publication_sessions) == {
        "tax_benefit_models": 2,
        "tax_benefit_model_versions": 4,
        "variables": 4,
        "parameter_nodes": 4,
        "parameters": 4,
        "parameter_values": 8,
        "datasets": 8,
        "dataset_versions": 0,
        "regions": 16,
        "simulations": 0,
        "reports": 0,
        "report_runs": 0,
    }


def test_publication_stores_every_value_shape_unchanged(
    publication_sessions: sessionmaker[Session],
) -> None:
    catalog = value_shape_catalog()

    publish_catalog(publication_sessions, catalog)
    # Publishing the same version again compares every stored row with the
    # catalog in both directions and fails on any difference, so this also
    # checks that the comparison reads each shape back as it was written.
    publish_catalog(publication_sessions, catalog)

    assert_catalog_stored_unchanged(publication_sessions, catalog)
    stored_values = stored_parameter_values(publication_sessions)
    us_model = catalog.country("us").model.name
    for case in PARAMETER_CASES:
        assert [
            value_json
            for (model_name, parameter_name, _start), (value_json, _end) in sorted(
                stored_values.items()
            )
            if (model_name, parameter_name) == (us_model, case.name)
        ] == [strict_json(value.stored_value) for value in case.values], case.name

    stored_regions = stored_catalog_rows(publication_sessions, "regions")
    filter_value_index = CATALOG_COLUMNS["regions"].index("filter_value") - 1
    for (country_id, code), filter_value in REGION_FILTER_VALUES.items():
        model_name = catalog.country(country_id).model.name
        stored_columns = json.loads(stored_regions[(model_name, code)])
        assert stored_columns[filter_value_index] == filter_value, code


def _format_2_values(sessions: sessionmaker[Session]) -> dict[str, object]:
    """Return the US version's stored catalog format 2 fields."""
    with sessions() as session:
        version = session.execute(
            select(
                col(TaxBenefitModelVersion.catalog_format),
                col(TaxBenefitModelVersion.entities),
                col(TaxBenefitModelVersion.basic_inputs),
            ).where(col(TaxBenefitModelVersion.id) == _us_version_id())
        ).one()
        variable = session.execute(
            sa.select(
                col(Variable.is_input_variable),
                col(Variable.hidden_input),
                col(Variable.module_name),
                col(Variable.adds_parameter_path),
                col(Variable.subtracts_parameter_path),
                col(Variable.enum_values),
                col(Variable.unit),
                col(Variable.definition_period),
            ).where(
                col(Variable.name) == "employment_income",
                col(Variable.tax_benefit_model_version_id) == _us_version_id(),
            )
        ).one()
        parameter = session.execute(
            select(col(Parameter.economy), col(Parameter.household)).where(
                col(Parameter.name) == "gov.example.rate",
                col(Parameter.tax_benefit_model_version_id) == _us_version_id(),
            )
        ).one()
    return {
        "version": tuple(version),
        "variable": tuple(variable),
        "parameter": tuple(parameter),
    }


def test_publication_stores_catalog_format_2_fields(
    publication_sessions: sessionmaker[Session],
) -> None:
    publish_catalog(publication_sessions, normalized_catalog())

    assert _format_2_values(publication_sessions) == {
        "version": (
            2,
            [
                {"key": "person", "plural": "people", "is_person": True},
                {"key": "household", "plural": "households", "is_person": False},
            ],
            ["employment_income"],
        ),
        "variable": (
            True,
            False,
            "household.income.employment_income",
            None,
            None,
            None,
            "currency-USD",
            "year",
        ),
        "parameter": (True, False),
    }


def test_version_stored_before_format_2_keeps_its_fields_empty_on_republish(
    publication_sessions: sessionmaker[Session],
) -> None:
    catalog = normalized_catalog()
    publish_catalog(publication_sessions, catalog)
    with publication_sessions.begin() as session:
        clear_format_2_fields(session)
    before_ids = _identifiers(publication_sessions)

    result = publish_catalog(publication_sessions, catalog)

    assert result.as_dict()["outcome"] == "ok"
    assert _identifiers(publication_sessions) == before_ids
    assert _format_2_values(publication_sessions) == {
        "version": (None, None, None),
        "variable": (None, None, None, None, None, None, None, None),
        "parameter": (None, None),
    }


def test_version_stored_with_format_2_fails_when_a_format_2_field_changes(
    publication_sessions: sessionmaker[Session],
) -> None:
    catalog = normalized_catalog()
    publish_catalog(publication_sessions, catalog)
    before_counts = _counts(publication_sessions)
    us = catalog.country("us")
    changed_parameter = replace(us.parameters[0], household=True)
    changed = replace(
        catalog,
        countries=(
            replace(us, parameters=(changed_parameter,)),
            catalog.country("uk"),
        ),
    )

    with pytest.raises(CatalogPublicationError, match="differs"):
        publish_catalog(publication_sessions, changed)

    assert _counts(publication_sessions) == before_counts
    assert _format_2_values(publication_sessions)["parameter"] == (True, False)


def _catalog_with_format_2_variable_records():
    models = source_models()
    add_format_2_variable_records(models["us"])
    return extract_catalog(
        bundle=bundle(),
        policyengine_version=POLICYENGINE_VERSION,
        models=models,
        installed_version=installed_version,
        region_references=region_references(),
    )


def _stored_us_variables(
    sessions: sessionmaker[Session],
) -> dict[str, tuple[object, ...]]:
    with sessions() as session:
        rows = session.execute(
            sa.select(
                col(Variable.name),
                col(Variable.enum_values),
                col(Variable.adds_parameter_path),
                col(Variable.subtracts_parameter_path),
                col(Variable.unit),
                col(Variable.definition_period),
            ).where(col(Variable.tax_benefit_model_version_id) == _us_version_id())
        ).all()
    return {row[0]: tuple(row[1:]) for row in rows}


def _with_changed_us_variable(catalog, name: str, **changes: object):
    us = catalog.country("us")
    variables = tuple(
        replace(variable, **changes) if variable.name == name else variable
        for variable in us.variables
    )
    return replace(
        catalog,
        countries=(replace(us, variables=variables), catalog.country("uk")),
    )


def test_enum_labels_parameter_paths_units_and_periods_round_trip_exactly(
    publication_sessions: sessionmaker[Session],
) -> None:
    catalog = _catalog_with_format_2_variable_records()

    publish_catalog(publication_sessions, catalog)
    before_ids = _identifiers(publication_sessions)
    stored = _stored_us_variables(publication_sessions)
    republished = publish_catalog(publication_sessions, catalog)

    assert stored["filing_status"] == (
        [{"value": "SINGLE", "label": "Single"}, {"value": "JOINT", "label": 2}],
        None,
        None,
        None,
        "year",
    )
    assert type(stored["filing_status"][0][1]["label"]) is int
    assert stored["countable_income"] == (
        None,
        "gov.example.countable_income",
        "gov.example.deductions",
        "currency-USD",
        "month",
    )
    assert republished.as_dict()["outcome"] == "ok"
    assert _identifiers(publication_sessions) == before_ids


@pytest.mark.parametrize(
    ("variable_name", "changes"),
    [
        (
            "filing_status",
            {
                "enum_values": (
                    EnumValueRecord(value="SINGLE", label="Single filer"),
                    EnumValueRecord(value="JOINT", label=2),
                )
            },
        ),
        ("countable_income", {"adds_parameter_path": "gov.example.deductions"}),
        ("countable_income", {"subtracts_parameter_path": None}),
        ("filing_status", {"unit": "currency-USD"}),
        ("countable_income", {"definition_period": "year"}),
    ],
)
def test_republication_detects_a_changed_enum_label_parameter_path_unit_or_period(
    publication_sessions: sessionmaker[Session],
    variable_name: str,
    changes: dict[str, object],
) -> None:
    catalog = _catalog_with_format_2_variable_records()
    publish_catalog(publication_sessions, catalog)
    stored = _stored_us_variables(publication_sessions)

    with pytest.raises(
        CatalogPublicationError,
        match=r"^the stored us catalog version 5\.0\.4 differs from the staged "
        r"catalog in its variables$",
    ):
        publish_catalog(
            publication_sessions,
            _with_changed_us_variable(catalog, variable_name, **changes),
        )

    assert _stored_us_variables(publication_sessions) == stored


def _stored_tree(
    sessions: sessionmaker[Session],
    model_name: str,
    version: str,
    *,
    by_parameter_id: bool = False,
) -> list[tuple]:
    """Return a stored version's tree rows; each parameter by name by default."""
    parameter_column = (
        col(ParameterTreeChild.parameter_id) if by_parameter_id else col(Parameter.name)
    )
    with sessions() as session:
        return [
            tuple(row)
            for row in session.execute(
                sa.select(
                    col(ParameterTreeChild.parent_path),
                    col(ParameterTreeChild.path),
                    col(ParameterTreeChild.position),
                    col(ParameterTreeChild.label),
                    col(ParameterTreeChild.child_type),
                    col(ParameterTreeChild.child_count),
                    col(ParameterTreeChild.reform_position),
                    col(ParameterTreeChild.reform_child_count),
                    parameter_column,
                    col(ParameterTreeChild.economy),
                    col(ParameterTreeChild.household),
                )
                .join(
                    TaxBenefitModelVersion,
                    col(TaxBenefitModelVersion.id)
                    == col(ParameterTreeChild.tax_benefit_model_version_id),
                )
                .join(
                    TaxBenefitModel,
                    col(TaxBenefitModel.id) == col(TaxBenefitModelVersion.model_id),
                )
                .outerjoin(
                    Parameter, col(Parameter.id) == col(ParameterTreeChild.parameter_id)
                )
                .where(
                    col(TaxBenefitModel.name) == model_name,
                    col(TaxBenefitModelVersion.version) == version,
                )
                .order_by(
                    col(ParameterTreeChild.parent_path),
                    col(ParameterTreeChild.position),
                )
            )
        ]


def _delete_tree(sessions: sessionmaker[Session], version: str) -> None:
    """Make the stored versions of one .py version look stored before the tree."""
    with sessions.begin() as session:
        session.execute(
            sa.delete(ParameterTreeChild).where(
                col(ParameterTreeChild.tax_benefit_model_version_id).in_(
                    _version_ids(version)
                )
            )
        )


FIXTURE_TREE = [
    ("", "gov", 0, "Gov", "node", 1, 0, 1, None, None, None),
    ("gov", "gov.example", 0, "Example policy", "node", 1, 0, 1, None, None, None),
    (
        "gov.example",
        "gov.example.rate",
        0,
        "Example rate",
        "parameter",
        None,
        0,
        None,
        "gov.example.rate",
        True,
        False,
    ),
]


def test_publication_writes_each_new_version_parameter_tree(
    publication_sessions: sessionmaker[Session],
) -> None:
    catalog = normalized_catalog()

    evidence = publish_catalog(publication_sessions, catalog)

    for country in catalog.countries:
        assert (
            _stored_tree(
                publication_sessions,
                country.model.name,
                country.model_version.version,
            )
            == FIXTURE_TREE
        )
    assert evidence.parameter_trees_written == tuple(
        (country.model.name, country.model_version.version, len(FIXTURE_TREE))
        for country in sorted(catalog.countries, key=lambda item: item.model.name)
    )


def _stored_tree_with_parameter_ids(
    sessions: sessionmaker[Session], model_name: str, version: str
) -> list[tuple]:
    return _stored_tree(sessions, model_name, version, by_parameter_id=True)


def _with_other_parameter_ids(catalog):
    """Return the catalog with a new ID for every parameter, and its values."""
    countries = []
    for country in catalog.countries:
        parameters = []
        for parameter in country.parameters:
            parameter_id = uuid4()
            parameters.append(
                replace(
                    parameter,
                    id=parameter_id,
                    values=tuple(
                        replace(value, id=uuid4(), parameter_id=parameter_id)
                        for value in parameter.values
                    ),
                )
            )
        countries.append(replace(country, parameters=tuple(parameters)))
    return replace(catalog, countries=tuple(countries))


def test_publication_gives_the_installed_stored_version_its_tree(
    publication_sessions: sessionmaker[Session],
) -> None:
    """The installed version, stored by a release without the tree, gets one.

    It is built from the installed packages' catalog, the same as a fresh
    publication's; writing it again changes nothing. The version is first
    stored with parameter IDs that differ from the catalog's, so the rebuilt
    tree must reference the stored rows' IDs.
    """
    catalog = normalized_catalog()
    current_version = catalog.country("us").model_version.version
    publish_catalog(publication_sessions, _with_other_parameter_ids(catalog))
    fresh = {
        country.model.name: _stored_tree_with_parameter_ids(
            publication_sessions, country.model.name, current_version
        )
        for country in catalog.countries
    }
    _delete_tree(publication_sessions, current_version)
    before_ids = _identifiers(publication_sessions)

    evidence = publish_catalog(publication_sessions, catalog)
    again = publish_catalog(publication_sessions, catalog)

    assert evidence.parameter_trees_written == tuple(
        (country.model.name, current_version, len(FIXTURE_TREE))
        for country in sorted(catalog.countries, key=lambda item: item.model.name)
    )
    assert again.parameter_trees_written == ()
    for country in catalog.countries:
        assert (
            _stored_tree_with_parameter_ids(
                publication_sessions, country.model.name, current_version
            )
            == fresh[country.model.name]
        )
    assert _identifiers(publication_sessions) == before_ids
    catalog_parameter_ids = {
        parameter.id
        for country in catalog.countries
        for parameter in country.parameters
    }
    for rows in fresh.values():
        assert {row[8] for row in rows if row[8] is not None}.isdisjoint(
            catalog_parameter_ids
        )


def test_an_installed_version_stored_before_format_2_gets_no_tree(
    publication_sessions: sessionmaker[Session],
) -> None:
    """A version stored before catalog format 2 stores no flags, so no tree.

    Its tree would carry the installed catalog's flags, which its own
    parameter rows do not store; it keeps returning the clear 503 instead, and
    publication still succeeds.
    """
    catalog = normalized_catalog()
    current_version = catalog.country("us").model_version.version
    publish_catalog(publication_sessions, catalog)
    with publication_sessions.begin() as session:
        clear_format_2_fields(session)
    _delete_tree(publication_sessions, current_version)

    evidence = publish_catalog(publication_sessions, catalog)

    assert evidence.as_dict()["outcome"] == "ok"
    assert evidence.parameter_trees_written == ()
    for country in catalog.countries:
        assert (
            _stored_tree(publication_sessions, country.model.name, current_version)
            == []
        )


def test_publication_writes_no_tree_for_another_version_stored_without_one(
    publication_sessions: sessionmaker[Session],
) -> None:
    """A stored version that is not the installed one keeps having no tree.

    Writing it would derive rows from what an earlier release stored, which
    the migration rules leave to a human migration decision.
    """
    older = normalized_catalog(policyengine_version="1.0.0")
    catalog = normalized_catalog()
    older_version = older.country("us").model_version.version
    publish_catalog(publication_sessions, older)
    _delete_tree(publication_sessions, older_version)

    evidence = publish_catalog(publication_sessions, catalog)
    again = publish_catalog(publication_sessions, catalog)

    assert {version for _model, version, _rows in evidence.parameter_trees_written} == {
        catalog.country("us").model_version.version
    }
    assert again.parameter_trees_written == ()
    for country in catalog.countries:
        assert (
            _stored_tree(publication_sessions, country.model.name, older_version) == []
        )


def test_publication_fails_when_a_published_version_is_left_without_a_tree(
    publication_sessions: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        publication_module,
        "write_parameter_trees",
        lambda _session, _countries: (),
    )

    with pytest.raises(CatalogPublicationError, match="has no parameter tree"):
        publish_catalog(publication_sessions, normalized_catalog())

    assert _counts(publication_sessions)["tax_benefit_model_versions"] == 0


def test_the_catalog_writer_role_publishes_the_parameter_tree(
    publication_sessions: sessionmaker[Session],
    v2_sessions_as_role: Callable[[str], sessionmaker[Session]],
) -> None:
    """Publication as the catalog writer, with only its declared privileges.

    It writes each published version's tree, which needs the role's INSERT
    grant on the tree table.
    """
    catalog = normalized_catalog()

    evidence = publish_catalog(v2_sessions_as_role(CATALOG_WRITER_ROLE), catalog)

    assert evidence.parameter_trees_written == tuple(
        (country.model.name, country.model_version.version, len(FIXTURE_TREE))
        for country in sorted(catalog.countries, key=lambda item: item.model.name)
    )
    for country in catalog.countries:
        assert (
            _stored_tree(
                publication_sessions,
                country.model.name,
                country.model_version.version,
            )
            == FIXTURE_TREE
        )


def _stored_search_file(
    sessions: sessionmaker[Session], model_name: str, version: str
) -> dict:
    """Return a stored version's search file, checking its hash and sizes."""
    with sessions() as session:
        row = session.execute(
            sa.select(
                col(ParameterSearchFile.file_format),
                col(ParameterSearchFile.compressed_content),
                col(ParameterSearchFile.content_sha256),
                col(ParameterSearchFile.uncompressed_size),
                col(ParameterSearchFile.compressed_size),
            )
            .join(
                TaxBenefitModelVersion,
                col(TaxBenefitModelVersion.id)
                == col(ParameterSearchFile.tax_benefit_model_version_id),
            )
            .join(
                TaxBenefitModel,
                col(TaxBenefitModel.id) == col(TaxBenefitModelVersion.model_id),
            )
            .where(
                col(TaxBenefitModel.name) == model_name,
                col(TaxBenefitModelVersion.version) == version,
            )
        ).one()
    content = gzip.decompress(row.compressed_content)
    assert row.file_format == 1
    assert row.content_sha256 == hashlib.sha256(content).hexdigest()
    assert row.uncompressed_size == len(content)
    assert row.compressed_size == len(row.compressed_content)
    return json.loads(content)


def _delete_search_files(sessions: sessionmaker[Session], version: str) -> None:
    """Make the stored versions of one .py version look stored before the files."""
    with sessions.begin() as session:
        session.execute(
            sa.delete(ParameterSearchFile).where(
                col(ParameterSearchFile.tax_benefit_model_version_id).in_(
                    _version_ids(version)
                )
            )
        )


def _search_file_count(sessions: sessionmaker[Session], version: str | None) -> int:
    """Count the stored search files, of one .py version's versions if given."""
    statement = sa.select(sa.func.count()).select_from(ParameterSearchFile)
    if version is not None:
        statement = statement.where(
            col(ParameterSearchFile.tax_benefit_model_version_id).in_(
                _version_ids(version)
            )
        )
    with sessions() as session:
        count: int = session.execute(statement).scalar_one()
    return count


def _fixture_search_file(country_id: str, version: str) -> dict:
    return {
        "format": 1,
        "country_id": country_id,
        "policyengine_version": version,
        "parameters": [
            {
                "path": "gov.example.rate",
                "label": "Example rate",
                "unit": "/1",
                "description": "An example rate",
                "editable": True,
            }
        ],
        "other_parameters": [],
        "nodes": [{"path": "gov.example", "label": "Example policy"}],
    }


def test_publication_writes_each_new_version_parameter_search_file(
    publication_sessions: sessionmaker[Session],
) -> None:
    catalog = normalized_catalog()

    evidence = publish_catalog(publication_sessions, catalog)

    for country in catalog.countries:
        version = country.model_version.version
        assert _stored_search_file(
            publication_sessions, country.model.name, version
        ) == _fixture_search_file(country.country_id, version)
    assert [
        (model_name, version)
        for model_name, version, _uncompressed, _compressed in (
            evidence.parameter_search_files_written
        )
    ] == [
        (country.model.name, country.model_version.version)
        for country in sorted(catalog.countries, key=lambda item: item.model.name)
    ]


def test_republication_writes_only_the_installed_version_search_file(
    publication_sessions: sessionmaker[Session],
) -> None:
    """A stored version gets its file only when its packages are installed.

    Files are built from the installed packages' catalog, never from rows an
    earlier release stored, so a version stored before search files existed
    gets its file when publication runs with its packages installed, and other
    stored versions are left without one.
    """
    older = normalized_catalog(policyengine_version="1.0.0")
    catalog = normalized_catalog()
    older_country_version = older.country("us").model_version.version
    current_country_version = catalog.country("us").model_version.version
    publish_catalog(publication_sessions, older)
    publish_catalog(publication_sessions, catalog)
    _delete_search_files(publication_sessions, older_country_version)
    _delete_search_files(publication_sessions, current_country_version)
    before_ids = _identifiers(publication_sessions)
    before_counts = _counts(publication_sessions)

    evidence = publish_catalog(publication_sessions, catalog)
    again = publish_catalog(publication_sessions, catalog)

    assert [
        (model_name, version)
        for model_name, version, _uncompressed, _compressed in (
            evidence.parameter_search_files_written
        )
    ] == [
        (country.model.name, current_country_version)
        for country in sorted(catalog.countries, key=lambda item: item.model.name)
    ]
    assert again.parameter_search_files_written == ()
    for country in catalog.countries:
        assert _stored_search_file(
            publication_sessions, country.model.name, current_country_version
        ) == _fixture_search_file(country.country_id, current_country_version)
    assert _search_file_count(publication_sessions, older_country_version) == 0
    assert _identifiers(publication_sessions) == before_ids
    assert _counts(publication_sessions) == before_counts


def test_republication_refuses_a_stored_search_file_that_differs(
    publication_sessions: sessionmaker[Session],
) -> None:
    catalog = normalized_catalog()
    publish_catalog(publication_sessions, catalog)
    with publication_sessions.begin() as session:
        session.execute(sa.update(ParameterSearchFile).values(content_sha256="0" * 64))

    with pytest.raises(
        CatalogPublicationError,
        match=r"stored parameter search file .* differs from the installed packages'",
    ):
        publish_catalog(publication_sessions, catalog)


def test_search_file_editability_follows_the_stored_current_law_values(
    publication_sessions: sessionmaker[Session],
) -> None:
    models = source_models()
    add_format_2_variable_records(models["us"])
    bracket_rate = SimpleNamespace(
        name="gov.example.bracket[1].rate",
        label=None,
        description=None,
        data_type=float,
        unit="/1",
        economy=True,
        household=True,
        parameter_values=[
            SimpleNamespace(
                value=0.02,
                start_date=datetime(2015, 1, 1, tzinfo=UTC),
                end_date=datetime(2020, 7, 7, tzinfo=UTC),
            ),
            SimpleNamespace(
                value=None,
                start_date=datetime(2020, 7, 8, tzinfo=UTC),
                end_date=datetime(2021, 3, 30, tzinfo=UTC),
            ),
            SimpleNamespace(
                value=0.02,
                start_date=datetime(2021, 3, 31, tzinfo=UTC),
                end_date=None,
            ),
        ],
    )
    models["us"].parameters.append(bracket_rate)
    models["us"].parameters_by_name[bracket_rate.name] = bracket_rate
    catalog = extract_catalog(
        bundle=bundle(),
        policyengine_version=POLICYENGINE_VERSION,
        models=models,
        installed_version=installed_version,
        region_references=region_references(),
    )

    publish_catalog(publication_sessions, catalog)

    us = catalog.country("us")
    search_file = _stored_search_file(
        publication_sessions, us.model.name, us.model_version.version
    )
    entries = {entry["path"]: entry for entry in search_file["parameters"]}
    assert entries["gov.example.bracket[1].rate"] == {
        "path": "gov.example.bracket[1].rate",
        "label": None,
        "unit": "/1",
        "description": None,
        "editable": True,
        "editable_changes": [
            {"start_date": "2020-07-08", "editable": False},
            {"start_date": "2021-03-31", "editable": True},
        ],
    }
    # A list of variable names is shown as "Can't be changed here".
    assert entries["gov.example.countable_income"]["editable"] is False
    assert entries["gov.example.deductions"]["editable"] is False
    assert entries["gov.example.rate"]["editable"] is True


def test_publication_fails_when_a_published_version_has_no_search_file(
    publication_sessions: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        publication_module,
        "write_parameter_search_files",
        lambda _session, _countries: (),
    )

    with pytest.raises(CatalogPublicationError, match="has no parameter search file"):
        publish_catalog(publication_sessions, normalized_catalog())

    assert _counts(publication_sessions)["tax_benefit_model_versions"] == 0


def test_the_catalog_writer_role_publishes_the_search_files(
    publication_sessions: sessionmaker[Session],
    v2_sessions_as_role: Callable[[str], sessionmaker[Session]],
) -> None:
    """Publication as the catalog writer writes each version's search file.

    That needs the role's declared INSERT grant on the search files' table.
    """
    catalog = normalized_catalog()

    evidence = publish_catalog(v2_sessions_as_role(CATALOG_WRITER_ROLE), catalog)

    assert [
        (model_name, version)
        for model_name, version, _uncompressed, _compressed in (
            evidence.parameter_search_files_written
        )
    ] == [
        (country.model.name, country.model_version.version)
        for country in sorted(catalog.countries, key=lambda item: item.model.name)
    ]
    for country in catalog.countries:
        version = country.model_version.version
        assert _stored_search_file(
            publication_sessions, country.model.name, version
        ) == _fixture_search_file(country.country_id, version)


def test_one_publication_gives_the_installed_stored_version_its_tree_and_file(
    publication_sessions: sessionmaker[Session],
) -> None:
    """The installed version stored without either gets both in one run."""
    catalog = normalized_catalog()
    current_version = catalog.country("us").model_version.version
    publish_catalog(publication_sessions, catalog)
    _delete_tree(publication_sessions, current_version)
    _delete_search_files(publication_sessions, current_version)

    evidence = publish_catalog(publication_sessions, catalog)

    model_names = [
        country.model.name
        for country in sorted(catalog.countries, key=lambda item: item.model.name)
    ]
    assert [model for model, _version, _rows in evidence.parameter_trees_written] == (
        model_names
    )
    assert [
        model
        for model, _version, _raw, _size in evidence.parameter_search_files_written
    ] == model_names
    for country in catalog.countries:
        assert (
            _stored_tree(publication_sessions, country.model.name, current_version)
            == FIXTURE_TREE
        )
        assert _stored_search_file(
            publication_sessions, country.model.name, current_version
        ) == _fixture_search_file(country.country_id, current_version)


def _mark_stored_before_catalog_format_2(
    sessions: sessionmaker[Session], version: str
) -> None:
    """Make the stored versions of one .py version look stored before format 2."""
    with sessions.begin() as session:
        session.execute(
            sa.update(TaxBenefitModelVersion)
            .where(col(TaxBenefitModelVersion.version) == version)
            .values(catalog_format=None)
        )


def test_an_installed_version_stored_before_catalog_format_2_gets_no_search_file(
    publication_sessions: sessionmaker[Session],
) -> None:
    """A version stored without format 2's flags keeps having no search file.

    Building its file from the installed catalog's flags would contradict the
    version's own stored parameter rows, so publication writes none for it and
    does not require one; the route then reports the version without a file.
    """
    catalog = normalized_catalog()
    current_version = catalog.country("us").model_version.version
    publish_catalog(publication_sessions, catalog)
    _delete_search_files(publication_sessions, current_version)
    _mark_stored_before_catalog_format_2(publication_sessions, current_version)

    evidence = publish_catalog(publication_sessions, catalog)

    assert evidence.parameter_search_files_written == ()
    assert _search_file_count(publication_sessions, None) == 0
