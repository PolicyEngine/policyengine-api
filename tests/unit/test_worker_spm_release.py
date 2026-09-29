"""Release checks compare installed packages with the selected worker."""

from copy import deepcopy

import pytest

from policyengine_api import constants, worker_spm, worker_spm_release
from policyengine_api.spm import SPMValidationError


BUNDLE_VERSION = "6.1.2"
PACKAGE_VERSIONS = {
    "policyengine": BUNDLE_VERSION,
    "policyengine-core": "3.32.5",
    "policyengine-us": "2.2.1",
    "policyengine-uk": "2.90.2",
    "spm-calculator": "1.0.0",
}
SELECTION = {
    "forecast_content_sha256": "a" * 64,
    "scenario": "fixture",
    "geography_kind": "county",
    "geography_id": None,
    "county_vintage": "2020",
    "as_of": None,
}
WORKER_APP = "fixture-worker"


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(constants, "POLICYENGINE_VERSION", BUNDLE_VERSION)
    monkeypatch.setattr(
        constants,
        "_policyengine_bundle",
        {
            "packages": {
                name: {"name": name, "version": package_version}
                for name, package_version in PACKAGE_VERSIONS.items()
            }
        },
    )
    monkeypatch.setattr(
        worker_spm_release,
        "distribution_version",
        PACKAGE_VERSIONS.__getitem__,
    )
    monkeypatch.setattr(worker_spm, "normalize_spm_selection", lambda *_: SELECTION)
    return {
        "policyengine": {BUNDLE_VERSION: WORKER_APP},
        "us": {PACKAGE_VERSIONS["policyengine-us"]: WORKER_APP},
        "uk": {PACKAGE_VERSIONS["policyengine-uk"]: WORKER_APP},
        "spm_capabilities": {
            BUNDLE_VERSION: {
                "contract_version": "canonical-spm-v1",
                "defaults": dict(SELECTION),
            }
        },
    }


def test_release_accepts_matching_installed_bundle_and_worker(registry):
    assert (
        worker_spm_release.validate_installed_worker(registry, BUNDLE_VERSION)
        == SELECTION
    )


@pytest.mark.parametrize(
    "mutation",
    ["missing-capability", "wrong-contract", "wrong-forecast"],
)
def test_release_rejects_worker_without_matching_spm_capability(registry, mutation):
    registry = deepcopy(registry)
    capability = registry["spm_capabilities"][BUNDLE_VERSION]
    if mutation == "missing-capability":
        registry["spm_capabilities"] = {}
    elif mutation == "wrong-contract":
        capability["contract_version"] = "different-contract"
    else:
        capability["defaults"]["forecast_content_sha256"] = "b" * 64

    with pytest.raises(SPMValidationError):
        worker_spm_release.validate_installed_worker(registry, BUNDLE_VERSION)


@pytest.mark.parametrize("route", ["policyengine", "us", "uk"])
def test_release_rejects_missing_worker_route(registry, route):
    registry[route] = {}
    with pytest.raises(ValueError, match="no .* application"):
        worker_spm_release.validate_installed_worker(registry, BUNDLE_VERSION)


@pytest.mark.parametrize("route", ["us", "uk"])
def test_release_rejects_country_route_to_different_worker(registry, route):
    version = next(iter(registry[route]))
    registry[route][version] = "different-worker"
    with pytest.raises(ValueError, match="different worker"):
        worker_spm_release.validate_installed_worker(registry, BUNDLE_VERSION)


def test_release_rejects_installed_distribution_outside_manifest(
    registry,
    monkeypatch,
):
    installed = {**PACKAGE_VERSIONS, "policyengine-core": "0.0.1"}
    monkeypatch.setattr(
        worker_spm_release,
        "distribution_version",
        installed.__getitem__,
    )
    with pytest.raises(ValueError, match="policyengine-core"):
        worker_spm_release.validate_installed_worker(registry, BUNDLE_VERSION)


def test_release_rejects_requirement_outside_manifest(registry):
    with pytest.raises(ValueError, match="manifest"):
        worker_spm_release.validate_installed_worker(registry, "7.0.0")


def test_release_rejects_manifest_without_complete_package_set(registry):
    constants._policyengine_bundle["packages"].pop("spm-calculator")
    with pytest.raises(ValueError, match="spm-calculator"):
        worker_spm_release.validate_installed_worker(registry, BUNDLE_VERSION)
