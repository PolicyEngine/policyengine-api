"""Release checks use the same certified selection boundary as HTTP requests."""

from copy import deepcopy

import pytest

from policyengine_api import constants, worker_spm, worker_spm_release
from policyengine_api.spm import SPMValidationError


DEFAULTS = {
    "forecast_content_sha256": "a" * 64,
    "scenario": "baseline",
    "geography_kind": "national",
    "geography_id": None,
    "county_vintage": "2020",
    "as_of": None,
}


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(worker_spm_release, "version", lambda _: "6.0.0")
    monkeypatch.setattr(constants, "POLICYENGINE_VERSION", "6.0.0")
    monkeypatch.setattr(worker_spm, "normalize_spm_selection", lambda *_: DEFAULTS)
    return {
        "policyengine": {"6.0.0": "canonical-worker"},
        "spm_capabilities": {
            "6.0.0": {"contract_version": "canonical-spm-v1", "defaults": DEFAULTS}
        },
    }


def test_release_accepts_matching_certified_worker(registry):
    assert worker_spm_release.validate_installed_worker(registry, "6.0.0") == DEFAULTS


@pytest.mark.parametrize(
    "mutation", ["absent", "wrong-contract", "wrong-hash", "wrong-version"]
)
def test_release_rejects_unusable_registered_worker(registry, mutation):
    registry = deepcopy(registry)
    capability = registry["spm_capabilities"]["6.0.0"]
    if mutation == "absent":
        registry["spm_capabilities"] = {}
    elif mutation == "wrong-contract":
        capability["contract_version"] = "other-contract"
    elif mutation == "wrong-hash":
        capability["defaults"]["forecast_content_sha256"] = "b" * 64
    else:
        registry["spm_capabilities"] = {"5.0.0": capability}
    with pytest.raises(SPMValidationError, match=""):
        worker_spm_release.validate_installed_worker(registry, "6.0.0")


def test_release_rejects_different_installed_bundle(registry):
    with pytest.raises(ValueError, match="installed"):
        worker_spm_release.validate_installed_worker(registry, "7.0.0")


@pytest.mark.parametrize("app", [None, "", {}, 123])
def test_release_rejects_invalid_registered_application(registry, app):
    registry["policyengine"]["6.0.0"] = app
    with pytest.raises(ValueError, match="application"):
        worker_spm_release.validate_installed_worker(registry, "6.0.0")


def test_release_accepts_legacy_without_capability(registry, monkeypatch):
    monkeypatch.setattr(worker_spm, "normalize_spm_selection", lambda *_: None)
    registry["spm_capabilities"] = {}
    assert worker_spm_release.validate_installed_worker(registry, "6.0.0") is None


def test_release_does_not_hide_uncertified_bundle(registry, monkeypatch):
    def unavailable(*_):
        raise SPMValidationError(
            "SPM_CONFIGURATION_UNAVAILABLE", "Missing certification"
        )

    monkeypatch.setattr(worker_spm, "normalize_spm_selection", unavailable)
    with pytest.raises(SPMValidationError):
        worker_spm_release.validate_installed_worker(registry, "6.0.0")


def test_release_rejects_different_runtime_selected_bundle(registry, monkeypatch):
    monkeypatch.setattr(constants, "POLICYENGINE_VERSION", "5.0.0")
    with pytest.raises(ValueError, match="runtime-selected"):
        worker_spm_release.validate_installed_worker(registry, "6.0.0")
