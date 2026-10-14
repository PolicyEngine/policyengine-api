"""Compatibility coverage for the complete installed PolicyEngine.py catalog."""

from __future__ import annotations

from importlib import metadata as importlib_metadata
import json
import os

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
    # Counts for the 6.3.4 bundle's models: US 2.2.1 and UK 2.126.12. Keep
    # this exact assertion so later package changes require explicit review.
    assert catalog.entity_counts() == {
        "models": 2,
        "model_versions": 2,
        "variables": 7_294,
        "parameter_nodes": 29_300,
        "parameters": 104_158,
        "parameter_values": 1_194_256,
        "datasets": 2,
        "regions": 826,
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
        "populace_us_2024"
    }
    assert {dataset.name for dataset in catalog.country("uk").datasets} == {
        "enhanced_frs_2024_25"
    }
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

    # 6.3.4 points US state and congressional-district regions at the national
    # dataset by explicit path (PolicyEngine/policyengine.py#604), so every US
    # region uses it and only places still fall back to it.
    us_catalog = catalog.country("us")
    us_dataset_names = {dataset.id: dataset.name for dataset in us_catalog.datasets}
    assert {
        us_dataset_names[region.default_dataset_id] for region in us_catalog.regions
    } == {"populace_us_2024"}
    assert [
        (summary.region_type, summary.count)
        for summary in us_catalog.fallback_summaries
    ] == [
        ("place", 333),
    ]
