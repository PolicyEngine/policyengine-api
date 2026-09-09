import json
from copy import deepcopy
from datetime import date
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ValidationError

from policyengine_api import spm


ARTIFACT_HASH = "a" * 64
LEGACY_BUNDLE = {
    "policyengine_version": "5.2.0",
    "packages": {"policyengine-us": {"version": "1.764.6"}},
}
CERTIFIED_SETTINGS = {
    "forecast_content_sha256": ARTIFACT_HASH,
    "scenario": "baseline",
}


@pytest.fixture
def certified_bundle(monkeypatch):
    bundle = {"measurements": {"spm": deepcopy(CERTIFIED_SETTINGS)}}
    monkeypatch.setattr(spm, "_current_bundle", lambda: bundle)
    monkeypatch.setattr(spm, "simulation_supports_spm", lambda _: True)

    def entry(year, *, scenario, as_of):
        if scenario not in {"baseline", "alternative"}:
            raise ValueError("Unknown forecast scenario")
        if as_of is not None and date.fromisoformat(as_of) < date(2026, 1, 1):
            raise ValueError("Forecast information date follows requested as_of")
        return {}

    def geography_factor(year, tenure, *, geoid, **kwargs):
        if geoid != "31080":
            raise ValueError("Forecast geography unavailable")
        return {}

    forecast = SimpleNamespace(
        years=(2022, 2035), entry=entry, geography_factor=geography_factor
    )
    monkeypatch.setattr(spm, "_selected_forecast", lambda expected: forecast)
    return bundle


@pytest.mark.parametrize(
    "selection",
    [
        {"unknown": True},
        {"forecast_content_sha256": "not-a-hash"},
        {"geography_kind": "state"},
        {"geography_kind": "national", "geography_id": "US"},
        {"geography_kind": "county", "geography_id": "06037"},
        {"geography_kind": "metro"},
        {"county_vintage": 2020},
        [],
    ],
)
def test_public_settings_reject_invalid_values(selection):
    with pytest.raises(ValidationError):
        spm.SPMSelection.model_validate(selection)


def test_public_settings_schema_forbids_extra_fields():
    assert spm.SPMSelection.model_json_schema()["additionalProperties"] is False


@pytest.mark.parametrize("country_id", ["uk", "ca", "ng", "il"])
def test_other_countries_omit_spm_without_reading_us_bundle(monkeypatch, country_id):
    def must_not_load():
        raise AssertionError("Non-US request must not read SPM configuration")

    monkeypatch.setattr(spm, "_current_bundle", must_not_load)
    assert spm.normalize_spm_selection(country_id, None) is None
    assert spm.spm_metadata(country_id) == {"available": False}
    with pytest.raises(spm.SPMValidationError) as caught:
        spm.normalize_spm_selection(country_id, {"geography_kind": "national"})
    assert caught.value.code == "SPM_SETTINGS_UNSUPPORTED"


@pytest.mark.parametrize("version", ["5.2.0", "5.3.0"])
def test_current_legacy_bundle_retains_omitted_selection(monkeypatch, version):
    bundle = {**LEGACY_BUNDLE, "policyengine_version": version}
    monkeypatch.setattr(spm, "_current_bundle", lambda: bundle)
    assert spm.normalize_spm_selection("us", None) is None
    assert spm.spm_metadata("us") == {"available": False}
    with pytest.raises(spm.SPMValidationError) as caught:
        spm.normalize_spm_selection("us", {})
    assert caught.value.to_dict()["code"] == "SPM_SETTINGS_UNSUPPORTED"


@pytest.mark.parametrize("version", ["5.3.1", "6.0.0", "5.2.1"])
def test_unknown_bundle_fails_closed_even_without_explicit_settings(
    monkeypatch, version
):
    bundle = {**LEGACY_BUNDLE, "policyengine_version": version}
    monkeypatch.setattr(spm, "_current_bundle", lambda: bundle)
    with pytest.raises(spm.SPMValidationError) as caught:
        spm.normalize_spm_selection("us", None)
    assert caught.value.code == "SPM_CONFIGURATION_UNAVAILABLE"
    assert spm.spm_metadata("us")["available"] is False


def test_default_and_explicit_default_have_identical_resolved_identity(
    certified_bundle,
):
    defaults = spm.normalize_spm_selection("us", None)
    assert defaults == spm.normalize_spm_selection("us", {})
    assert defaults == spm.normalize_spm_selection(
        "us", {"forecast_content_sha256": None, "scenario": None}
    )
    assert defaults == {
        "forecast_content_sha256": ARTIFACT_HASH,
        "scenario": "baseline",
        "geography_kind": "county",
        "geography_id": None,
        "county_vintage": "2020",
        "as_of": None,
    }


@pytest.mark.parametrize(
    "selection",
    [
        {"geography_kind": "national"},
        {"geography_kind": "metro", "geography_id": "31080"},
        {"scenario": "alternative"},
        {"as_of": "2026-09-09"},
    ],
)
def test_selection_changes_resolved_request_identity(certified_bundle, selection):
    default = spm.normalize_spm_selection("us", None)
    chosen = spm.normalize_spm_selection("us", selection)
    assert chosen != default
    for key, value in selection.items():
        assert chosen[key] == value


@pytest.mark.parametrize(
    "selection",
    [
        {"forecast_content_sha256": "b" * 64},
        {"scenario": "unknown-scenario"},
        {"as_of": "2020-01-01"},
        {"as_of": "yesterday"},
        {"county_vintage": "2010"},
        {"geography_kind": "national", "geography_id": "US"},
        {"unreviewed_setting": True},
    ],
)
def test_invalid_selected_artifact_settings_have_structured_error(
    certified_bundle, selection
):
    with pytest.raises(spm.SPMValidationError) as caught:
        spm.normalize_spm_selection("us", selection)
    assert caught.value.code == "SPM_SETTINGS_INVALID"
    assert caught.value.to_dict()["message"]


def test_certification_requires_pinned_artifact_hash(certified_bundle):
    certified_bundle["measurements"]["spm"].pop("forecast_content_sha256")
    with pytest.raises(spm.SPMValidationError) as caught:
        spm.normalize_spm_selection("us", None)
    assert caught.value.code == "SPM_CONFIGURATION_UNAVAILABLE"


def test_mismatched_installed_artifact_cannot_enable_metadata(
    certified_bundle, monkeypatch
):
    def mismatched_artifact(expected):
        assert expected == ARTIFACT_HASH
        raise ValueError("Forecast content SHA256 mismatch")

    monkeypatch.setattr(spm, "_selected_forecast", mismatched_artifact)
    with pytest.raises(spm.SPMValidationError) as caught:
        spm.normalize_spm_selection("us", {"geography_kind": "national"})
    assert caught.value.code == "SPM_CONFIGURATION_UNAVAILABLE"
    assert spm.spm_metadata("us") == {"available": False}


def test_legacy_country_cannot_enable_certified_settings(certified_bundle, monkeypatch):
    monkeypatch.setattr(spm, "simulation_supports_spm", lambda _: False)
    with pytest.raises(spm.SPMValidationError) as caught:
        spm.normalize_spm_selection("us", None)
    assert caught.value.code == "SPM_CONFIGURATION_UNAVAILABLE"


def test_metadata_exposes_typed_defaults_only_when_available(certified_bundle):
    result = spm.spm_metadata("us")
    assert result["available"] is True
    assert result["defaults"] == spm.normalize_spm_selection("us", None)
    assert result["settings_schema"] == spm.SPMSelection.model_json_schema()


def test_selected_area_must_exist_in_artifact(certified_bundle):
    with pytest.raises(spm.SPMValidationError) as caught:
        spm.normalize_spm_selection(
            "us", {"geography_kind": "metro", "geography_id": "unknown-area"}
        )
    assert caught.value.code == "SPM_GEOGRAPHY_UNAVAILABLE"


def test_area_available_in_later_year_can_be_selected(certified_bundle, monkeypatch):
    def geography_factor(year, tenure, **kwargs):
        if year < 2025:
            raise ValueError("Area unavailable before the boundary changed")
        return {}

    forecast = SimpleNamespace(
        years=(2022, 2035),
        entry=lambda *args, **kwargs: {},
        geography_factor=geography_factor,
    )
    monkeypatch.setattr(spm, "_selected_forecast", lambda _: forecast)
    assert (
        spm.normalize_spm_selection(
            "us", {"geography_kind": "metro", "geography_id": "later-area"}
        )["geography_id"]
        == "later-area"
    )


@pytest.mark.parametrize("wrapped", [False, True])
def test_missing_forecast_year_message_alone_does_not_reclassify_errors(wrapped):
    try:
        raise ValueError("Forecast has no entry for 2036")
    except ValueError as error:
        if wrapped:
            outer = RuntimeError("An unrelated dependency failed")
            outer.__cause__ = error
            error = outer
        assert spm.spm_error_detail(error) is None


def test_plain_forecast_missing_year_is_not_reclassified():
    forecast_module = pytest.importorskip("spm_calculator.rolling_forecast")
    forecast = forecast_module.load_forecast()
    year = max(forecast.years) + 1
    with pytest.raises(ValueError) as caught:
        forecast.entry(year)
    assert spm.spm_error_detail(caught.value) is None


def test_other_real_forecast_errors_are_not_reclassified():
    forecast_module = pytest.importorskip("spm_calculator.rolling_forecast")
    forecast = forecast_module.load_forecast()
    with pytest.raises(ValueError) as caught:
        forecast.entry(forecast.years[0], scenario="unknown-scenario")
    assert spm.spm_error_detail(caught.value) is None


@pytest.mark.parametrize("status", [400, 422])
def test_typed_worker_year_error_is_preserved(status):
    import httpx

    from policyengine_api.worker_spm import raise_worker_spm_error

    detail = {
        "code": "SPM_YEAR_UNAVAILABLE",
        "message": "Forecast has no entry for 2036",
    }
    with pytest.raises(spm.SPMValidationError) as caught:
        raise_worker_spm_error(httpx.Response(status, json={"errors": [detail]}))
    assert caught.value.to_dict() == detail


def test_variadic_constructor_alone_does_not_claim_support():
    class Legacy:
        def __init__(self, **kwargs):
            pass

    class Canonical(Legacy):
        spm_config = property(lambda self: {})

        def spm_provenance(self):
            return {}

    assert spm.simulation_supports_spm(Legacy) is False
    assert spm.simulation_supports_spm(Canonical) is True


@pytest.mark.parametrize("code", sorted(spm.SPM_INPUT_ERROR_CODES))
def test_error_recognition_includes_wrapped_country_dependencies(code):
    error = ValueError("Explicit household input required")
    error.code = code
    wrapped = RuntimeError("Error calculating dependent variable")
    wrapped.__cause__ = error
    assert spm.spm_error_detail(wrapped) == {
        "code": code,
        "message": "Explicit household input required",
    }
    assert spm.spm_error_detail(ValueError("unrelated failure")) is None


@pytest.mark.parametrize(
    "geography",
    [
        {"geography_kind": "national"},
        {"geography_kind": "metro", "geography_id": "31080"},
    ],
)
@pytest.mark.parametrize(
    "selection", [{}, {"scenario": "alternative"}, {"as_of": None}]
)
def test_partial_selection_preserves_bundle_defaults_across_json(
    certified_bundle, geography, selection
):
    class Request(BaseModel):
        spm: spm.SPMSelection

    certified_bundle["measurements"]["spm"].update(geography)
    chosen = spm.SPMSelection.model_validate(selection)
    wire = json.loads(Request(spm=chosen).model_dump_json())["spm"]
    assert wire == selection
    before = spm.normalize_spm_selection("us", chosen)
    after = spm.normalize_spm_selection("us", wire)
    assert before == after
    assert all(after[key] == value for key, value in geography.items())
    assert set(after) == set(spm.SPMSelection.model_fields)
    assert json.loads(spm.SPMSelection.model_validate(after).model_dump_json()) == after


@pytest.mark.parametrize("kind", ["national", "county"])
def test_explicit_geography_change_clears_inherited_metro_id(certified_bundle, kind):
    certified_bundle["measurements"]["spm"].update(
        geography_kind="metro", geography_id="31080"
    )
    resolved = spm.normalize_spm_selection("us", {"geography_kind": kind})
    assert resolved["geography_kind"] == kind
    assert resolved["geography_id"] is None


def test_selection_schema_does_not_force_inherited_options():
    schema = spm.SPMSelection.model_json_schema()
    assert "required" not in schema
    assert all("default" not in prop for prop in schema["properties"].values())


@pytest.mark.parametrize("version", ["5.2.0", "5.3.0"])
def test_known_legacy_wrapper_with_different_country_fails_closed(monkeypatch, version):
    monkeypatch.setattr(
        spm,
        "_current_bundle",
        lambda: {
            "policyengine_version": version,
            "packages": {"policyengine-us": {"version": "1.824.7"}},
        },
    )
    with pytest.raises(spm.SPMValidationError, match="no certified"):
        spm.normalize_spm_selection("us", None)
