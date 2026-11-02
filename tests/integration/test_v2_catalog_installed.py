"""Compatibility coverage for the complete installed PolicyEngine.py catalog."""

from __future__ import annotations

import json
import os
from importlib import metadata as importlib_metadata

import pytest
from policyengine.bundle import get_current_bundle

from policyengine_api.data.v2.catalog.extraction import extract_installed_catalog

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_V2_CATALOG_COMPATIBILITY") != "1",
    reason=("loads the complete public catalog; set RUN_V2_CATALOG_COMPATIBILITY=1"),
)


def test_installed_policyengine_catalog_is_complete_and_bounded() -> None:
    catalog = extract_installed_catalog()
    bundle = get_current_bundle()
    policyengine_version = importlib_metadata.version("policyengine")
    expected_dependencies = tuple(
        (name, bundle["packages"][name]["version"])
        for name in (
            "policyengine-core",
            "policyengine-us",
            "policyengine-uk",
        )
    )

    assert catalog.policyengine_version == policyengine_version
    assert catalog.dependency_versions == expected_dependencies
    assert all(
        importlib_metadata.version(name) == expected
        for name, expected in expected_dependencies
    )
    # Counts for the 6.11.1 bundle's models: US 2.2.1 and UK 2.151.0. Keep
    # this exact assertion so later package changes require explicit review.
    # Since 6.10.0 the UK registry also lists its 650 constituencies and 361
    # local authorities, because the bundle routes them to a local-area
    # release, so regions grow by 1,011 from 6.7.5's 826 and the catalog
    # adds that release's dataset.
    assert catalog.entity_counts() == {
        "models": 2,
        "model_versions": 2,
        "variables": 7_438,
        "parameter_nodes": 29_367,
        "parameters": 104_673,
        "parameter_values": 1_196_139,
        "datasets": 4,
        "regions": 1_837,
    }

    for country_id in ("us", "uk"):
        country = catalog.country(country_id)
        assert country.model.name == f"policyengine-{country_id}"
        assert country.model_version.version == policyengine_version
        assert country.model_version.version not in dict(expected_dependencies).values()
        assert country.variables
        assert country.parameter_nodes
        assert all("__pycache__" not in node.name for node in country.parameter_nodes)
        assert country.parameters
        assert all(
            not dataset.is_output_dataset and dataset.storage_path is None
            for dataset in country.datasets
        )

        total_values = 0
        for batch in country.parameter_value_batches(batch_size=10_000):
            assert 0 < len(batch) <= 10_000
            total_values += len(batch)
        assert total_values == country.entity_counts()["parameter_values"]

    assert {dataset.name for dataset in catalog.country("us").datasets} == {
        "populace_us_2024",
        "populace_us_2024_acs_local",
    }
    assert {dataset.name for dataset in catalog.country("uk").datasets} == {
        "microcosm_uk_2024_25",
        "microcosm_uk_2024_25_dense",
    }
    # The national file has no area codes, so UK constituencies and local
    # authorities use the local-area dataset .py routes them to, while the
    # UK countries filter the national file.
    uk_catalog = catalog.country("uk")
    uk_dataset_names = {dataset.id: dataset.name for dataset in uk_catalog.datasets}
    uk_region_type_datasets: dict[str, set[str]] = {}
    for region in uk_catalog.regions:
        uk_region_type_datasets.setdefault(region.region_type, set()).add(
            uk_dataset_names[region.default_dataset_id]
        )
    assert uk_region_type_datasets == {
        "national": {"microcosm_uk_2024_25"},
        "country": {"microcosm_uk_2024_25"},
        "constituency": {"microcosm_uk_2024_25_dense"},
        "local_authority": {"microcosm_uk_2024_25_dense"},
    }
    assert uk_catalog.fallback_summaries == ()
    england = next(
        region
        for region in catalog.country("uk").regions
        if region.code == "country/england"
    )
    assert england.filter_field == "region"
    assert england.filter_strategy == "row_filter"
    assert england.filter_value is not None
    assert json.loads(england.filter_value) == [
        "NORTH_EAST",
        "NORTH_WEST",
        "YORKSHIRE",
        "EAST_MIDLANDS",
        "WEST_MIDLANDS",
        "EAST_OF_ENGLAND",
        "LONDON",
        "SOUTH_EAST",
        "SOUTH_WEST",
    ]

    # Since 6.7.5, US state and congressional-district regions use the
    # ACS-local dataset again, on the PolicyEngine/microcosm#1263 rebuild
    # (PolicyEngine/policyengine.py#649, ending #604's national-file filter).
    # The national region uses the national dataset, and places fall back to it.
    us_catalog = catalog.country("us")
    us_dataset_names = {dataset.id: dataset.name for dataset in us_catalog.datasets}
    region_type_datasets: dict[str, set[str]] = {}
    for region in us_catalog.regions:
        region_type_datasets.setdefault(region.region_type, set()).add(
            us_dataset_names[region.default_dataset_id]
        )
    assert region_type_datasets == {
        "national": {"populace_us_2024"},
        "state": {"populace_us_2024_acs_local"},
        "congressional_district": {"populace_us_2024_acs_local"},
        "place": {"populace_us_2024"},
    }
    assert [
        (summary.region_type, summary.count)
        for summary in us_catalog.fallback_summaries
    ] == [
        ("place", 333),
    ]
