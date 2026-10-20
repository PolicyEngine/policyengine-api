"""Focused extraction tests for the PolicyEngine.py v2 catalog."""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from enum import Enum
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from types import SimpleNamespace

import pytest

from policyengine_api.data.v2.catalog.extraction import (
    CatalogExtractionError,
    extract_catalog,
    normalize_json_value,
)
from policyengine_api.data.v2.catalog.records import CATALOG_FORMAT
from tests.fixtures.v2_catalog import (
    DEPENDENCY_VERSIONS,
    POLICYENGINE_VERSION,
    ParameterScale,
    bundle,
    installed_version,
    normalized_catalog,
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
        "populace_us_ca_2024",
    }
    assert {dataset.name for dataset in uk.datasets} == {"enhanced_frs_2024_25"}
    assert all(
        not dataset.is_output_dataset for dataset in (*us.datasets, *uk.datasets)
    )
    assert all(dataset.storage_path is None for dataset in (*us.datasets, *uk.datasets))

    us_datasets = {dataset.id: dataset.name for dataset in us.datasets}
    us_defaults = {
        region.code: us_datasets[region.default_dataset_id] for region in us.regions
    }
    assert us_defaults == {
        "place/CA-44000": "populace_us_2024",
        "state/ca": "populace_us_ca_2024",
        "us": "populace_us_2024",
    }
    assert [
        (summary.region_type, summary.count) for summary in us.fallback_summaries
    ] == [("place", 1)]
    assert all(region.default_dataset_id == uk.datasets[0].id for region in uk.regions)


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


@pytest.mark.parametrize("value", [("NORTH_EAST", "LONDON"), ["NORTH_EAST", "LONDON"]])
def test_serializes_region_membership_filters_in_the_existing_text_field(
    value: object,
) -> None:
    models = source_models()
    models["uk"].region_registry[1].scoping_strategy.variable_value = value

    catalog = extract_catalog(
        bundle=bundle(),
        policyengine_version=POLICYENGINE_VERSION,
        models=models,
        installed_version=installed_version,
    )
    england = next(
        region
        for region in catalog.country("uk").regions
        if region.code == "country/england"
    )

    assert isinstance(england.filter_value, str)
    assert json.loads(england.filter_value) == ["NORTH_EAST", "LONDON"]


@pytest.mark.parametrize("value", ["ENGLAND", 6, True, 1.5])
def test_preserves_existing_scalar_region_filter_serialization(value: object) -> None:
    models = source_models()
    models["uk"].region_registry[1].scoping_strategy.variable_value = value

    catalog = extract_catalog(
        bundle=bundle(),
        policyengine_version=POLICYENGINE_VERSION,
        models=models,
        installed_version=installed_version,
    )
    england = next(
        region
        for region in catalog.country("uk").regions
        if region.code == "country/england"
    )

    assert england.filter_value == str(value)


@pytest.mark.parametrize(
    "value",
    [[], [["LONDON"]], [None], [object()], [float("nan")], ["x" * 256], "x" * 256],
)
def test_rejects_invalid_or_oversized_region_membership_values(value: object) -> None:
    models = source_models()
    models["uk"].region_registry[1].scoping_strategy.variable_value = value

    with pytest.raises(CatalogExtractionError, match="filter value"):
        extract_catalog(
            bundle=bundle(),
            policyengine_version=POLICYENGINE_VERSION,
            models=models,
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
            bundle=missing,
            policyengine_version=POLICYENGINE_VERSION,
            models=source_models(),
            installed_version=installed_version,
        )

    with pytest.raises(CatalogExtractionError, match="does not match"):
        extract_catalog(
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
            bundle=bundle(),
            policyengine_version=POLICYENGINE_VERSION,
            models=source_models(),
            installed_version=absent,
        )


@pytest.mark.parametrize("version", ["", "0.0.0", "unknown"])
def test_rejects_placeholder_policyengine_versions(version: str) -> None:
    with pytest.raises(CatalogExtractionError, match="placeholder"):
        extract_catalog(
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
            bundle=bundle(),
            policyengine_version=POLICYENGINE_VERSION,
            models=models,
            installed_version=installed_version,
        )

    models = source_models()
    models["us"].release_manifest.default_dataset = "unreviewed_us_2025"
    with pytest.raises(CatalogExtractionError, match="reviewed selection"):
        extract_catalog(
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
            bundle=bundle(),
            policyengine_version=POLICYENGINE_VERSION,
            models=models,
            installed_version=installed_version,
        )


def test_rejects_duplicate_keys_invalid_intervals_and_unknown_region_types() -> None:
    duplicate = source_models()
    duplicate["us"].parameters_by_name = []
    with pytest.raises(CatalogExtractionError, match="name-indexed mapping"):
        extract_catalog(
            bundle=bundle(),
            policyengine_version=POLICYENGINE_VERSION,
            models=duplicate,
            installed_version=installed_version,
        )

    unknown_region = source_models()
    unknown_region["us"].region_registry[1].region_type = "province"
    with pytest.raises(CatalogExtractionError, match="unsupported type"):
        extract_catalog(
            bundle=bundle(),
            policyengine_version=POLICYENGINE_VERSION,
            models=unknown_region,
            installed_version=installed_version,
        )

    invalid_interval = source_models()
    invalid_interval["us"].parameters_by_name["gov.example.rate"].parameter_values[
        0
    ].end_date = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(CatalogExtractionError, match="canonical inclusive intervals"):
        extract_catalog(
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


def test_extracts_presentation_metadata_through_the_country_system() -> None:
    us = normalized_catalog().country("us")
    variable = us.variables[0]
    parameter = us.parameters[0]

    assert us.model_version.catalog_format == CATALOG_FORMAT
    assert us.model_version.basic_inputs == ("employment_income",)
    assert us.model_version.entities == (
        {
            "key": "person",
            "plural": "people",
            "label": "Person",
            "description": "An individual.",
            "is_person": True,
            "roles": [],
        },
        {
            "key": "household",
            "plural": "households",
            "label": "Household",
            "description": "A household.",
            "is_person": False,
            "roles": [
                {
                    "key": "member",
                    "plural": "members",
                    "label": "Member",
                    "description": None,
                }
            ],
        },
    )
    assert (
        variable.value_type,
        variable.definition_period,
        variable.unit,
        variable.module_name,
        variable.is_input_variable,
        variable.hidden_input,
        variable.possible_value_labels,
    ) == ("float", "year", "currency-USD", "household.income", True, False, None)
    assert (
        parameter.metadata_label,
        parameter.period,
        parameter.economy,
        parameter.household,
    ) == ("Rate", "year", True, False)


def test_parameters_without_flags_default_to_economy_and_household() -> None:
    models = source_models()
    core_parameter = models["uk"]._load_system().parameters.get_descendants()[1]
    core_parameter.metadata = {}

    catalog = extract_catalog(
        bundle=bundle(),
        policyengine_version=POLICYENGINE_VERSION,
        models=models,
        installed_version=installed_version,
    )
    parameter = catalog.country("uk").parameters[0]

    assert (parameter.metadata_label, parameter.period) == (None, None)
    assert (parameter.economy, parameter.household) == (True, True)


def test_enum_variables_keep_each_value_label() -> None:
    models = source_models()

    class Region(Enum):
        NORTH_EAST = "North East"
        LONDON = "London"

    public_variable = models["uk"].variables_by_name["employment_income"]
    public_variable.value_type = type("Enum", (), {})
    public_variable.possible_values = ["NORTH_EAST", "LONDON"]
    core_variable = models["uk"]._load_system().variables["employment_income"]
    core_variable.possible_values = Region

    catalog = extract_catalog(
        bundle=bundle(),
        policyengine_version=POLICYENGINE_VERSION,
        models=models,
        installed_version=installed_version,
    )
    variable = catalog.country("uk").variables[0]

    assert variable.value_type == "Enum"
    assert variable.possible_values == ["NORTH_EAST", "LONDON"]
    assert variable.possible_value_labels == {
        "NORTH_EAST": "North East",
        "LONDON": "London",
    }


def test_adds_labelled_bracket_schedules_the_public_model_omits() -> None:
    models = source_models()
    system = models["us"]._load_system()
    descendants = system.parameters.get_descendants()
    schedule = ParameterScale(
        name="gov.example.schedule",
        metadata={"label": "Example schedule"},
        description="Rates by income band",
    )
    system.parameters.get_descendants = lambda: [*descendants, schedule]

    catalog = extract_catalog(
        bundle=bundle(),
        policyengine_version=POLICYENGINE_VERSION,
        models=models,
        installed_version=installed_version,
    )
    nodes = {node.name: node for node in catalog.country("us").parameter_nodes}

    assert nodes["gov.example"].is_scale is False
    assert nodes["gov.example.schedule"].is_scale is True
    assert nodes["gov.example.schedule"].label == "Example schedule"
    assert nodes["gov.example.schedule"].description == "Rates by income band"
    assert catalog.country("us").entity_counts()["parameter_nodes"] == 2


def test_rejects_a_public_model_without_its_country_system() -> None:
    models = source_models()
    del models["us"]._load_system

    with pytest.raises(CatalogExtractionError, match="country system"):
        extract_catalog(
            bundle=bundle(),
            policyengine_version=POLICYENGINE_VERSION,
            models=models,
            installed_version=installed_version,
        )


@pytest.mark.parametrize("record_kind", ["variables", "parameters"])
def test_rejects_records_missing_from_the_country_system(record_kind: str) -> None:
    models = source_models()
    system = models["us"]._load_system()
    if record_kind == "variables":
        system.variables.clear()
    else:
        system.parameters.get_descendants = list

    with pytest.raises(CatalogExtractionError, match="absent from the country system"):
        extract_catalog(
            bundle=bundle(),
            policyengine_version=POLICYENGINE_VERSION,
            models=models,
            installed_version=installed_version,
        )


def test_rejects_enum_labels_that_do_not_match_the_possible_values() -> None:
    models = source_models()

    class Region(Enum):
        NORTH_EAST = "North East"

    public_variable = models["uk"].variables_by_name["employment_income"]
    public_variable.value_type = type("Enum", (), {})
    public_variable.possible_values = ["NORTH_EAST", "LONDON"]
    core_variable = models["uk"]._load_system().variables["employment_income"]
    core_variable.possible_values = Region

    with pytest.raises(CatalogExtractionError, match="enum labels do not match"):
        extract_catalog(
            bundle=bundle(),
            policyengine_version=POLICYENGINE_VERSION,
            models=models,
            installed_version=installed_version,
        )


@pytest.mark.parametrize(
    ("flag_name", "flag_value"),
    [("economy", "false"), ("household", 1)],
)
def test_rejects_parameter_flags_that_are_not_booleans(
    flag_name: str, flag_value: object
) -> None:
    models = source_models()
    core_parameter = models["uk"]._load_system().parameters.get_descendants()[1]
    core_parameter.metadata = {**core_parameter.metadata, flag_name: flag_value}

    with pytest.raises(CatalogExtractionError, match=f"{flag_name} must be a boolean"):
        extract_catalog(
            bundle=bundle(),
            policyengine_version=POLICYENGINE_VERSION,
            models=models,
            installed_version=installed_version,
        )


def test_rejects_variable_flags_that_are_not_booleans() -> None:
    models = source_models()
    core_variable = models["uk"]._load_system().variables["employment_income"]
    core_variable.hidden_input = "no"

    with pytest.raises(CatalogExtractionError, match="hidden_input must be a boolean"):
        extract_catalog(
            bundle=bundle(),
            policyengine_version=POLICYENGINE_VERSION,
            models=models,
            installed_version=installed_version,
        )
