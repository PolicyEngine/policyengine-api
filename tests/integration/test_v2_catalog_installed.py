"""Compatibility coverage for the complete installed PolicyEngine.py catalog."""

from __future__ import annotations

import json
import os
from collections import Counter
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
    # Counts for the 6.7.5 bundle's models: US 2.2.1 and UK 2.130.1. Keep
    # this exact assertion so later package changes require explicit review.
    assert catalog.entity_counts() == {
        "models": 2,
        "model_versions": 2,
        "variables": 7_330,
        "parameter_nodes": 29_306,
        "parameters": 104_171,
        "parameter_values": 1_194_357,
        "datasets": 3,
        "regions": 1_503,
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

    # Since 6.7.5, US state and congressional-district regions use the
    # ACS-local dataset again, on the PolicyEngine/microcosm#1263 rebuild
    # (PolicyEngine/policyengine.py#649, ending #604's national-file filter).
    # The national region uses the national dataset. Regions come from the
    # checked-in reference files; US places cannot run yet and are left out.
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
    }
    assert us_catalog.fallback_summaries == ()
    assert [
        (summary.region_type, summary.count)
        for summary in us_catalog.omitted_region_summaries
    ] == [("place", 333)]

    uk_catalog = catalog.country("uk")
    uk_types = Counter(region.region_type for region in uk_catalog.regions)
    assert uk_types == {
        "national": 1,
        "country": 4,
        "constituency": 650,
        "local_authority": 360,
    }
    uk_regions = {region.code: region for region in uk_catalog.regions}
    aldershot = uk_regions["constituency/E14001063"]
    assert (
        aldershot.filter_strategy,
        aldershot.filter_field,
        aldershot.filter_value,
    ) == ("weight_replacement", "parliamentary_constituency_weights", "E14001063")
    assert uk_regions["uk"].label == "United Kingdom"
    assert {region.code: region.label for region in us_catalog.regions}["us"] == (
        "United States"
    )
