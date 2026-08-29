"""Compatibility coverage for the complete installed PolicyEngine.py catalog."""

from __future__ import annotations

from importlib import metadata as importlib_metadata
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
    assert catalog.entity_counts() == {
        "models": 2,
        "model_versions": 2,
        "variables": 6_649,
        "parameter_nodes": 27_813,
        "parameters": 99_006,
        "parameter_values": 1_172_130,
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
    assert [
        (summary.region_type, summary.count)
        for summary in catalog.country("us").fallback_summaries
    ] == [
        ("congressional_district", 436),
        ("place", 333),
        ("state", 51),
    ]
