"""Focused extraction tests for the PolicyEngine.py v2 catalog."""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from types import SimpleNamespace

import pytest

from policyengine_api.data.v2.catalog.extraction import (
    CatalogExtractionError,
    extract_catalog,
    normalize_json_value,
)
from tests.fixtures.v2_catalog import (
    DEPENDENCY_VERSIONS,
    POLICYENGINE_VERSION,
    bundle,
    installed_version,
    normalized_catalog,
    region_references,
    source_models,
)


def test_extracts_canonical_policyengine_catalog_and_dataset_defaults() -> None:
    catalog = normalized_catalog()
    us = catalog.country("us")
    uk = catalog.country("uk")

    assert catalog.policyengine_version == POLICYENGINE_VERSION
    assert dict(catalog.dependency_versions) == DEPENDENCY_VERSIONS
    assert us.model_version.version == POLICYENGINE_VERSION
    assert us.model_version.version != DEPENDENCY_VERSIONS["policyengine-us"]
    assert uk.model_version.version != DEPENDENCY_VERSIONS["policyengine-uk"]

    assert {dataset.name for dataset in us.datasets} == {
        "populace_us_2024",
        "populace_us_2024_acs_local",
    }
    assert {dataset.name for dataset in uk.datasets} == {"microcosm_uk_2024_25"}
    assert all(
        not dataset.is_output_dataset for dataset in (*us.datasets, *uk.datasets)
    )
    assert all(dataset.storage_path is None for dataset in (*us.datasets, *uk.datasets))

    us_datasets = {dataset.id: dataset.name for dataset in us.datasets}
    us_defaults = {
        region.code: us_datasets[region.default_dataset_id] for region in us.regions
    }
    assert us_defaults == {
        "congressional_district/CA-01": "populace_us_2024_acs_local",
        "state/ca": "populace_us_2024_acs_local",
        "us": "populace_us_2024",
    }
    assert us.fallback_summaries == ()
    assert [
        (summary.region_type, summary.count) for summary in us.omitted_region_summaries
    ] == [("place", 1)]
    assert uk.omitted_region_summaries == ()
    assert all(region.default_dataset_id == uk.datasets[0].id for region in uk.regions)


def test_regions_take_labels_from_references_and_filters_from_scoping_rules() -> None:
    catalog = normalized_catalog()
    regions = {
        region.code: (
            region.label,
            region.region_type,
            region.parent_code,
            region.requires_filter,
            region.filter_strategy,
            region.filter_field,
            region.filter_value,
            region.state_code,
            region.state_name,
        )
        for country_id in ("us", "uk")
        for region in catalog.country(country_id).regions
    }

    assert regions == {
        "us": ("United States", "national", None, False, None, None, None, None, None),
        "state/ca": (
            "California",
            "state",
            "us",
            True,
            "row_filter",
            "state_fips",
            "6",
            "CA",
            "California",
        ),
        "congressional_district/CA-01": (
            "California's 1st congressional district",
            "congressional_district",
            "state/ca",
            True,
            "row_filter",
            "congressional_district_geoid",
            "601",
            "CA",
            "California",
        ),
        "uk": ("United Kingdom", "national", None, False, None, None, None, None, None),
        "country/england": (
            "England",
            "country",
            "uk",
            True,
            "row_filter",
            "region",
            '["NORTH_EAST","LONDON"]',
            None,
            None,
        ),
        "constituency/E14001063": (
            "Aldershot",
            "constituency",
            "country/england",
            True,
            "weight_replacement",
            "parliamentary_constituency_weights",
            "E14001063",
            None,
            None,
        ),
    }


def test_sub_national_regions_without_a_release_dataset_use_the_default() -> None:
    models = source_models()
    del models["us"].release_manifest.region_datasets["state"]
    del models["us"].release_manifest.region_datasets["congressional_district"]

    us = extract_catalog(
        region_references=region_references(),
        bundle=bundle(),
        policyengine_version=POLICYENGINE_VERSION,
        models=models,
        installed_version=installed_version,
    ).country("us")

    assert {dataset.name for dataset in us.datasets} == {"populace_us_2024"}
    assert all(region.default_dataset_id == us.datasets[0].id for region in us.regions)
    assert [
        (summary.region_type, summary.count) for summary in us.fallback_summaries
    ] == [("congressional_district", 1), ("state", 1)]


def test_durable_ids_are_deterministic_and_stable_at_the_intended_scope() -> None:
    first = normalized_catalog()
    repeated = normalized_catalog()
    newer = normalized_catalog(policyengine_version="5.0.5")

    assert first == repeated
    for country_id in ("us", "uk"):
        old = first.country(country_id)
        new = newer.country(country_id)
        assert old.model.id == new.model.id
        assert old.model_version.id != new.model_version.id
        assert {dataset.id for dataset in old.datasets}.isdisjoint(
            dataset.id for dataset in new.datasets
        )
        assert {region.id for region in old.regions}.isdisjoint(
            region.id for region in new.regions
        )
        assert all(
            dataset.model_version_id == old.model_version.id for dataset in old.datasets
        )
        assert all(
            region.model_version_id == old.model_version.id for region in old.regions
        )


def test_parameter_values_are_nested_and_iterated_in_bounded_batches() -> None:
    us = normalized_catalog().country("us")

    assert len(us.parameters) == 1
    assert len(us.parameters[0].values) == 2
    assert [len(batch) for batch in us.parameter_value_batches(batch_size=1)] == [
        1,
        1,
    ]
    assert [len(batch) for batch in us.parameter_value_batches(batch_size=100)] == [2]
    with pytest.raises(ValueError, match="positive"):
        tuple(us.parameter_value_batches(batch_size=0))


def test_normalizes_supported_json_scalars_dates_and_containers() -> None:
    class Scalar:
        def item(self):
            return 7

    assert normalize_json_value(
        {
            "date": datetime(2026, 1, 1, tzinfo=UTC),
            "values": (Scalar(), True, 1.5),
        }
    ) == {
        "date": "2026-01-01T00:00:00+00:00",
        "values": [7, True, 1.5],
    }
    assert normalize_json_value(float("inf")) == "Infinity"
    assert normalize_json_value(float("-inf")) == "-Infinity"


@pytest.mark.parametrize("value", ['["NORTH_EAST","LONDON"]', "ENGLAND", "6"])
def test_keeps_reference_filter_values_as_text(value: str) -> None:
    references = region_references()
    england = references["uk"][1]
    references["uk"] = (
        references["uk"][0],
        replace(england, filter_value=value),
        references["uk"][2],
    )

    catalog = extract_catalog(
        region_references=references,
        bundle=bundle(),
        policyengine_version=POLICYENGINE_VERSION,
        models=source_models(),
        installed_version=installed_version,
    )
    england_record = next(
        region
        for region in catalog.country("uk").regions
        if region.code == "country/england"
    )

    assert england_record.filter_value == value


@pytest.mark.parametrize(
    "value",
    ["[]", '[["LONDON"]]', "[null]", '[{"a": 1}]', "[NaN]", "[", '{"a": 1}'],
)
def test_rejects_filter_value_lists_that_are_not_flat_json_scalars(
    value: str,
) -> None:
    references = region_references()
    england = references["uk"][1]
    references["uk"] = (
        references["uk"][0],
        replace(england, filter_value=value),
        references["uk"][2],
    )

    with pytest.raises(
        CatalogExtractionError,
        match=r"^region 'country/england' has an unsupported filter value$",
    ):
        extract_catalog(
            region_references=references,
            bundle=bundle(),
            policyengine_version=POLICYENGINE_VERSION,
            models=source_models(),
            installed_version=installed_version,
        )


@pytest.mark.parametrize("value", [float("nan"), object(), {1: "x"}])
def test_rejects_non_json_values(value: object) -> None:
    with pytest.raises(CatalogExtractionError):
        normalize_json_value(value)


def test_rejects_missing_or_mismatched_manifest_dependencies() -> None:
    missing = bundle()
    del missing["packages"]["policyengine-core"]
    with pytest.raises(CatalogExtractionError, match="omits policyengine-core"):
        extract_catalog(
            region_references=region_references(),
            bundle=missing,
            policyengine_version=POLICYENGINE_VERSION,
            models=source_models(),
            installed_version=installed_version,
        )

    with pytest.raises(CatalogExtractionError, match="does not match"):
        extract_catalog(
            region_references=region_references(),
            bundle=bundle(),
            policyengine_version=POLICYENGINE_VERSION,
            models=source_models(),
            installed_version=lambda name: (
                "wrong" if name == "policyengine-us" else installed_version(name)
            ),
        )

    def absent(_name: str) -> str:
        raise PackageNotFoundError

    with pytest.raises(CatalogExtractionError, match="is absent"):
        extract_catalog(
            region_references=region_references(),
            bundle=bundle(),
            policyengine_version=POLICYENGINE_VERSION,
            models=source_models(),
            installed_version=absent,
        )


@pytest.mark.parametrize("version", ["", "0.0.0", "unknown"])
def test_rejects_placeholder_policyengine_versions(version: str) -> None:
    with pytest.raises(CatalogExtractionError, match="placeholder"):
        extract_catalog(
            region_references=region_references(),
            bundle=bundle(policyengine_version=version),
            policyengine_version=version,
            models=source_models(policyengine_version=version),
            installed_version=installed_version,
        )


def test_rejects_incomplete_public_model_catalogs() -> None:
    models = source_models()
    del models["uk"]
    with pytest.raises(CatalogExtractionError, match="absent for: uk"):
        extract_catalog(
            region_references=region_references(),
            bundle=bundle(),
            policyengine_version=POLICYENGINE_VERSION,
            models=models,
            installed_version=installed_version,
        )

    models = source_models()
    models["us"].release_manifest.default_dataset = "unreviewed_us_2025"
    with pytest.raises(CatalogExtractionError, match="reviewed selection"):
        extract_catalog(
            region_references=region_references(),
            bundle=bundle(),
            policyengine_version=POLICYENGINE_VERSION,
            models=models,
            installed_version=installed_version,
        )


@pytest.mark.parametrize("identity_source", ["model", "model_package"])
def test_rejects_inconsistent_country_model_identity(identity_source: str) -> None:
    models = source_models()
    if identity_source == "model":
        models["us"].model.id = "unexpected-us-model"
    else:
        models["us"].model_package.name = "unexpected-us-package"

    with pytest.raises(CatalogExtractionError, match="identity does not match"):
        extract_catalog(
            region_references=region_references(),
            bundle=bundle(),
            policyengine_version=POLICYENGINE_VERSION,
            models=models,
            installed_version=installed_version,
        )


def test_ignores_only_the_unnamed_structural_parameter_root() -> None:
    models = source_models()
    models["uk"].parameter_nodes_by_name[""] = SimpleNamespace(
        name="", label=None, description=None
    )

    catalog = extract_catalog(
        region_references=region_references(),
        bundle=bundle(),
        policyengine_version=POLICYENGINE_VERSION,
        models=models,
        installed_version=installed_version,
    )

    assert [node.name for node in catalog.country("uk").parameter_nodes] == [
        "gov.example"
    ]


def test_uses_and_validates_public_name_indexed_mappings() -> None:
    models = source_models()
    variable = models["uk"].variables_by_name.pop("employment_income")
    models["uk"].variables_by_name["wrong_name"] = variable
    with pytest.raises(CatalogExtractionError, match="does not match record name"):
        extract_catalog(
            region_references=region_references(),
            bundle=bundle(),
            policyengine_version=POLICYENGINE_VERSION,
            models=models,
            installed_version=installed_version,
        )


def test_rejects_unindexed_mappings_and_invalid_parameter_intervals() -> None:
    duplicate = source_models()
    duplicate["us"].parameters_by_name = []
    with pytest.raises(CatalogExtractionError, match="name-indexed mapping"):
        extract_catalog(
            region_references=region_references(),
            bundle=bundle(),
            policyengine_version=POLICYENGINE_VERSION,
            models=duplicate,
            installed_version=installed_version,
        )

    invalid_interval = source_models()
    invalid_interval["us"].parameters_by_name["gov.example.rate"].parameter_values[
        0
    ].end_date = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(CatalogExtractionError, match="canonical inclusive intervals"):
        extract_catalog(
            region_references=region_references(),
            bundle=bundle(),
            policyengine_version=POLICYENGINE_VERSION,
            models=invalid_interval,
            installed_version=installed_version,
        )


def test_rejects_parameter_values_that_are_not_oldest_to_newest() -> None:
    models = source_models()
    parameter = models["us"].parameters_by_name["gov.example.rate"]
    parameter.parameter_values.reverse()
    with pytest.raises(CatalogExtractionError, match="oldest to newest"):
        extract_catalog(
            region_references=region_references(),
            bundle=bundle(),
            policyengine_version=POLICYENGINE_VERSION,
            models=models,
            installed_version=installed_version,
        )


def test_collapses_equal_parameter_values_at_the_same_effective_date() -> None:
    models = source_models()
    parameter = models["us"].parameters_by_name["gov.example.rate"]
    repeated = parameter.parameter_values[1]
    parameter.parameter_values.append(
        SimpleNamespace(
            value=repeated.value,
            start_date=repeated.start_date,
            end_date=repeated.end_date,
        )
    )

    catalog = extract_catalog(
        region_references=region_references(),
        bundle=bundle(),
        policyengine_version=POLICYENGINE_VERSION,
        models=models,
        installed_version=installed_version,
    )

    values = catalog.country("us").parameters[0].values
    assert [(value.start_date, value.value_json) for value in values] == [
        (datetime(2025, 1, 1, tzinfo=UTC), 0.1),
        (datetime(2026, 1, 1, tzinfo=UTC), 0.2),
    ]


def test_rejects_conflicting_parameter_values_at_the_same_effective_date() -> None:
    models = source_models()
    parameter = models["us"].parameters_by_name["gov.example.rate"]
    repeated = parameter.parameter_values[1]
    parameter.parameter_values.append(
        SimpleNamespace(
            value=0.3,
            start_date=repeated.start_date,
            end_date=repeated.end_date,
        )
    )

    with pytest.raises(CatalogExtractionError, match="conflicting values"):
        extract_catalog(
            region_references=region_references(),
            bundle=bundle(),
            policyengine_version=POLICYENGINE_VERSION,
            models=models,
            installed_version=installed_version,
        )


def test_rejects_repeated_parameter_values_with_inconsistent_intervals() -> None:
    models = source_models()
    parameter = models["us"].parameters_by_name["gov.example.rate"]
    repeated = parameter.parameter_values[1]
    parameter.parameter_values.append(
        SimpleNamespace(
            value=repeated.value,
            start_date=repeated.start_date,
            end_date=repeated.start_date,
        )
    )

    with pytest.raises(CatalogExtractionError, match="inconsistent intervals"):
        extract_catalog(
            region_references=region_references(),
            bundle=bundle(),
            policyengine_version=POLICYENGINE_VERSION,
            models=models,
            installed_version=installed_version,
        )


def test_preserves_consecutive_day_parameter_value_intervals() -> None:
    models = source_models()
    parameter = models["us"].parameters_by_name["gov.example.rate"]
    parameter.parameter_values = [
        SimpleNamespace(
            value=0.1,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            end_date=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        SimpleNamespace(
            value=0.2,
            start_date=datetime(2026, 1, 2, tzinfo=UTC),
            end_date=None,
        ),
    ]

    catalog = extract_catalog(
        region_references=region_references(),
        bundle=bundle(),
        policyengine_version=POLICYENGINE_VERSION,
        models=models,
        installed_version=installed_version,
    )

    values = catalog.country("us").parameters[0].values
    assert values[0].start_date == values[0].end_date
    assert values[1].start_date == datetime(2026, 1, 2, tzinfo=UTC)
    assert values[1].end_date is None


def test_extractor_has_no_direct_core_country_or_v1_metadata_imports() -> None:
    source_path = (
        Path(__file__).parents[3]
        / "policyengine_api"
        / "data"
        / "v2"
        / "catalog"
        / "extraction.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }

    assert not any(
        module.startswith(
            (
                "policyengine_core",
                "policyengine_us",
                "policyengine_uk",
                "policyengine_api.country",
                "policyengine_api.services.metadata_service",
            )
        )
        for module in imported_modules
    )
