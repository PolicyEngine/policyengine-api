"""Characterization of each outcome of resolving an SPM selection against a bundle."""

from copy import deepcopy
from datetime import date
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from policyengine_api import spm

ARTIFACT_HASH = "a" * 64
OTHER_HASH = "b" * 64
CERTIFIED_SETTINGS = {
    "forecast_content_sha256": ARTIFACT_HASH,
    "scenario": "baseline",
}
RESOLVED_DEFAULTS = {
    "forecast_content_sha256": ARTIFACT_HASH,
    "scenario": "baseline",
    "geography_kind": "county",
    "geography_id": None,
    "county_vintage": "2020",
    "as_of": None,
}


def _forecast() -> SimpleNamespace:
    def entry(_year, *, scenario, as_of):
        if scenario not in {"baseline", "alternative"}:
            msg = "Unknown forecast scenario"
            raise ValueError(msg)
        if as_of is not None and date.fromisoformat(as_of) < date(2026, 1, 1):
            msg = "Forecast information date follows requested as_of"
            raise ValueError(msg)
        return {}

    def geography_factor(_year, _tenure, *, geoid, **_kwargs):
        if geoid != "31080":
            msg = "Forecast geography unavailable"
            raise ValueError(msg)
        return {}

    return SimpleNamespace(
        years=(2022, 2035), entry=entry, geography_factor=geography_factor
    )


@pytest.fixture
def install_bundle(monkeypatch):
    """Install a bundle manifest and choose whether the US model supports SPM."""

    def install(bundle: object, *, model_supports_spm: bool = True) -> None:
        monkeypatch.setattr(spm, "_current_bundle", lambda: deepcopy(bundle))
        monkeypatch.setattr(
            spm, "simulation_supports_spm", lambda _: model_supports_spm
        )
        monkeypatch.setattr(
            spm,
            "_installed_country_implements_spm",
            lambda _country_id: model_supports_spm,
        )
        monkeypatch.setattr(spm, "_selected_forecast", lambda _expected: _forecast())

    return install


CERTIFIED = {"measurements": {"spm": CERTIFIED_SETTINGS}}
UNCONFIGURED = {"measurements": {}}

FAILURES = {
    "other-country-with-settings": (
        "uk",
        {},
        CERTIFIED,
        True,
        False,
        ("SPM_SETTINGS_UNSUPPORTED", "SPM settings are only available for the US"),
        None,
    ),
    "invalid-settings": (
        "us",
        {"geography_kind": "state"},
        CERTIFIED,
        True,
        False,
        ("SPM_SETTINGS_INVALID", None),
        ValidationError,
    ),
    "settings-not-an-object": (
        "us",
        [],
        CERTIFIED,
        True,
        False,
        ("SPM_SETTINGS_INVALID", None),
        ValidationError,
    ),
    "manifest-not-an-object": (
        "us",
        None,
        ["not", "a", "manifest"],
        True,
        False,
        ("SPM_CONFIGURATION_UNAVAILABLE", "The installed bundle manifest is invalid"),
        None,
    ),
    "capable-model-without-configuration": (
        "us",
        None,
        UNCONFIGURED,
        True,
        False,
        (
            "SPM_CONFIGURATION_UNAVAILABLE",
            "The installed bundle has no certified SPM measurement configuration",
        ),
        None,
    ),
    "legacy-model-with-settings": (
        "us",
        {"geography_kind": "national"},
        {"measurements": None},
        False,
        False,
        (
            "SPM_SETTINGS_UNSUPPORTED",
            "This US model bundle does not support canonical SPM settings",
        ),
        None,
    ),
    "configuration-without-pinned-hash": (
        "us",
        None,
        {"measurements": {"spm": {"scenario": "baseline"}}},
        True,
        False,
        (
            "SPM_CONFIGURATION_UNAVAILABLE",
            "The bundle must pin the SPM artifact hash and scenario",
        ),
        ValueError,
    ),
    "requested-other-artifact": (
        "us",
        {"forecast_content_sha256": OTHER_HASH},
        CERTIFIED,
        True,
        False,
        (
            "SPM_SETTINGS_INVALID",
            "SPM selection does not match this bundle's artifact hash",
        ),
        None,
    ),
    "stored-other-artifact": (
        "us",
        {"forecast_content_sha256": OTHER_HASH},
        CERTIFIED,
        True,
        True,
        (
            "SPM_CONFIGURATION_UNAVAILABLE",
            "This deployment does not have the SPM artifact this household's "
            "saved selection was measured against",
        ),
        None,
    ),
    "unknown-scenario": (
        "us",
        {"scenario": "nowhere"},
        CERTIFIED,
        True,
        False,
        ("SPM_SETTINGS_INVALID", "Unknown forecast scenario"),
        ValueError,
    ),
    "unsupported-county-vintage": (
        "us",
        {"county_vintage": "2010"},
        CERTIFIED,
        True,
        True,
        ("SPM_SETTINGS_INVALID", "Unsupported county vintage: use 2020"),
        ValueError,
    ),
    "unavailable-metro": (
        "us",
        {"geography_kind": "metro", "geography_id": "99999"},
        CERTIFIED,
        True,
        False,
        (
            "SPM_GEOGRAPHY_UNAVAILABLE",
            "SPM area is unavailable in the selected artifact: 99999",
        ),
        None,
    ),
}


@pytest.mark.parametrize("case_name", sorted(FAILURES))
def test_each_rejected_selection_has_its_code_message_and_cause(
    case_name, install_bundle
):
    country_id, selection, bundle, supports_spm, stored, expected, cause_type = (
        FAILURES[case_name]
    )
    install_bundle(bundle, model_supports_spm=supports_spm)
    expected_code, expected_message = expected

    with pytest.raises(spm.SPMValidationError) as caught:
        spm.normalize_spm_selection(country_id, selection, stored=stored)

    assert caught.value.code == expected_code
    if expected_message is None:
        assert caught.value.message
    else:
        assert caught.value.message == expected_message
    if cause_type is None:
        assert caught.value.__cause__ is None
    else:
        assert type(caught.value.__cause__) is cause_type


RESOLVED = {
    "other-country-without-settings": ("uk", None, CERTIFIED, True, None),
    "legacy-model-without-settings": ("us", None, UNCONFIGURED, False, None),
    "defaults": ("us", None, CERTIFIED, True, RESOLVED_DEFAULTS),
    "explicit-matching-hash": (
        "us",
        {"forecast_content_sha256": ARTIFACT_HASH, "scenario": "alternative"},
        CERTIFIED,
        True,
        {**RESOLVED_DEFAULTS, "scenario": "alternative"},
    ),
    "available-metro": (
        "us",
        {"geography_kind": "metro", "geography_id": "31080"},
        CERTIFIED,
        True,
        {**RESOLVED_DEFAULTS, "geography_kind": "metro", "geography_id": "31080"},
    ),
    "national-with-information-date": (
        "us",
        {"geography_kind": "national", "as_of": "2026-03-01"},
        CERTIFIED,
        True,
        {**RESOLVED_DEFAULTS, "geography_kind": "national", "as_of": "2026-03-01"},
    ),
}


@pytest.mark.parametrize("case_name", sorted(RESOLVED))
def test_each_accepted_selection_resolves_to_its_identity(case_name, install_bundle):
    country_id, selection, bundle, supports_spm, expected = RESOLVED[case_name]
    install_bundle(bundle, model_supports_spm=supports_spm)

    assert spm.normalize_spm_selection(country_id, selection) == expected
