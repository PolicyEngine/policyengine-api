"""Fixtures for the execution receipt compatibility contract."""

from copy import deepcopy

import pytest


MODEL_SHA256 = "a" * 64
DATASET_SHA256 = "b" * 64
DATASET_BUILD_ID = "release-1"
DATASET_URI = "hf://policyengine/populace-us/populace_us_2024.h5@release-1"

POLICYENGINE_BUNDLE_MANIFEST = {
    "schema_version": 2,
    "policyengine_version": "4.18.9",
    "data_releases": {
        "us": {
            "schema_version": 1,
            "bundle_id": "us-4.18.9",
            "country_id": "us",
            "policyengine_version": "4.18.9",
            "model_package": {
                "name": "policyengine-us",
                "version": "1.752.2",
                "sha256": MODEL_SHA256,
                "wheel_url": "https://files.example/policyengine_us-1.752.2.whl",
            },
            "data_package": {
                "name": "populace-data",
                "version": "0.1.0",
                "repo_id": "policyengine/populace-us",
                "repo_type": "dataset",
                "release_manifest_path": "releases/release-1/release_manifest.json",
                "release_manifest_revision": DATASET_BUILD_ID,
            },
            "default_dataset": "populace_us_2024",
            "datasets": {
                "populace_us_2024": {
                    "path": "populace_us_2024.h5",
                    "revision": DATASET_BUILD_ID,
                    "sha256": DATASET_SHA256,
                    "repo_id": "policyengine/populace-us",
                }
            },
            "region_datasets": {"national": {"path_template": "populace_us_2024.h5"}},
            "certified_data_artifact": {
                "data_package": {
                    "name": "populace-data",
                    "version": "0.1.0",
                },
                "dataset": "populace_us_2024",
                "uri": DATASET_URI,
                "sha256": DATASET_SHA256,
                "build_id": DATASET_BUILD_ID,
            },
            "certification": {
                "compatibility_basis": "built_with_model_package",
                "certified_for_model_version": "1.752.2",
                "data_build_id": DATASET_BUILD_ID,
                "built_with_model_version": "1.752.2",
                "certified_by": "policyengine.py bundle certification",
            },
        }
    },
}

HOUSEHOLD_REQUEST = {
    "household": {"people": {"you": {}}},
    "policy": {},
}
HOUSEHOLD_RESULT = {"people": {"you": {"age": {"2026": 40}}}}
ECONOMY_RESULT = {
    "poverty_impact": {"baseline": 0.12, "reform": 0.10},
}
ECONOMY_POLICYENGINE_BUNDLE = {
    "model_version": "1.752.2",
    "policyengine_version": "4.18.9",
    "data_version": DATASET_BUILD_ID,
    "dataset": DATASET_URI,
}

INSTALLED_PACKAGE_VERSIONS = {
    "policyengine": "4.18.9",
    "policyengine-core": "3.28.0",
    "policyengine-us": "1.752.2",
}


@pytest.fixture
def mock_execution_receipt_runtime(monkeypatch):
    """Provide stable installed and certified package identities."""
    from policyengine_api import execution_receipt

    monkeypatch.setattr(
        execution_receipt,
        "get_policyengine_bundle_manifest",
        lambda: deepcopy(POLICYENGINE_BUNDLE_MANIFEST),
    )
    monkeypatch.setattr(
        execution_receipt,
        "_get_installed_package_version",
        lambda package_name: INSTALLED_PACKAGE_VERSIONS.get(package_name),
    )
