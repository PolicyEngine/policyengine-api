"""Public SPM settings and the certified US bundle boundary.

Household geography and composition are checked by the country only when an
SPM dependency is calculated. Resolving these settings never calculates one.
"""

from __future__ import annotations

import importlib
import inspect
from functools import lru_cache
from datetime import date
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_serializer,
    model_validator,
)


class SPMSelection(BaseModel):
    """Select a forecast scenario and an explicit household SPM geography."""

    @staticmethod
    def _selection_schema(schema):
        # Omitted fields inherit the certified bundle, which may select a
        # different geography. Generated clients must preserve that omission.
        for field in schema.get("properties", {}).values():
            field.pop("default", None)
        schema["oneOf"] = [
            {
                "properties": {"geography_kind": {"enum": ["county", "national"]}},
                "not": {
                    "required": ["geography_id"],
                    "properties": {"geography_id": {"type": "string"}},
                },
            },
            {
                "required": ["geography_kind", "geography_id"],
                "properties": {
                    "geography_kind": {"enum": ["metro"]},
                    "geography_id": {
                        "type": "string",
                        "minLength": 1,
                        "pattern": r"\S",
                    },
                },
            },
        ]

    model_config = ConfigDict(
        frozen=True, extra="forbid", json_schema_extra=_selection_schema
    )
    forecast_content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    scenario: str | None = Field(default=None, min_length=1, pattern=r"^\S+$")
    geography_kind: Literal["county", "national", "metro"] = "county"
    geography_id: str | None = Field(default=None, min_length=1)
    county_vintage: str = Field(default="2020", pattern=r"^[0-9]{4}$")
    as_of: str | None = Field(
        default=None,
        description="ISO calendar date (YYYY-MM-DD); must satisfy the selected artifact's information date",
        json_schema_extra={
            "format": "date",
            "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
        },
    )

    @model_serializer(mode="wrap")
    def serialize_selection(self, handler):
        """Keep omitted options distinct from explicit choices in nested JSON."""
        return {
            name: value
            for name, value in handler(self).items()
            if name in self.model_fields_set
        }

    @field_validator("as_of")
    @classmethod
    def validate_as_of(cls, value):
        if value is not None and date.fromisoformat(value).isoformat() != value:
            raise ValueError("as_of must be an ISO calendar date (YYYY-MM-DD)")
        return value

    @model_validator(mode="after")
    def validate_location(self):
        if self.geography_kind == "metro":
            if not self.geography_id or not self.geography_id.strip():
                raise ValueError("An SPM area selection requires geography_id")
        elif self.geography_id is not None:
            raise ValueError("Only an SPM area selection accepts geography_id")
        return self


class SPMProvenance(BaseModel):
    """JSON receipt matching the country's public provenance contract."""

    model_config = ConfigDict(extra="forbid")
    forecast_id: str
    forecast_sha256: str
    scenario: str
    geography_kind: str
    runtime_versions: dict[str, str | None]
    years: dict[str, dict[str, Any]]
    geographies: list[dict[str, Any]]
    composition_method: str
    storage_method: str


class SPMValidationError(ValueError):
    """An SPM request/configuration error safe for the API's 4xx envelope."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


SPM_INPUT_ERROR_CODES = frozenset(
    {
        "SPM_GEOGRAPHY_REQUIRED",
        "SPM_GEOGRAPHY_UNAVAILABLE",
        "SPM_COMPOSITION_REQUIRED",
        "SPM_YEAR_UNAVAILABLE",
    }
)


def spm_error_detail(error: BaseException) -> dict[str, str] | None:
    """Recognize country errors, including those wrapped by dependency tracing."""
    visited = set()
    while error is not None and id(error) not in visited:
        visited.add(id(error))
        if isinstance(error, SPMValidationError) or (
            isinstance(error, ValueError)
            and getattr(error, "code", None) in SPM_INPUT_ERROR_CODES
        ):
            return {"code": error.code, "message": str(error)}
        error = error.__cause__ or error.__context__
    return None


def simulation_supports_spm(simulation_type) -> bool:
    """Old US constructors also accept **kwargs, so that alone is insufficient."""
    parameters = inspect.signature(simulation_type).parameters
    return "spm" in parameters or (
        hasattr(simulation_type, "spm_config")
        and callable(getattr(simulation_type, "spm_provenance", None))
    )


def _current_bundle() -> dict:
    from policyengine_api.constants import _policyengine_bundle

    return _policyengine_bundle


def _legacy_bundle(bundle: dict) -> bool:
    # Both verified published bundles use the same legacy country implementation.
    # A new unconfigured bundle must not inherit this exception by version range.
    version = bundle.get("policyengine_version") or bundle.get("bundle_version")
    packages = bundle.get("packages")
    us = packages.get("policyengine-us", {}) if isinstance(packages, dict) else {}
    if not isinstance(us, dict):
        return False
    return version in {"5.2.0", "5.3.0"} and us.get("version") == "1.764.6"


@lru_cache(maxsize=4)
def _selected_forecast(expected_sha256: str):
    from spm_calculator.rolling_forecast import load_forecast

    return load_forecast(expected_sha256=expected_sha256)


def normalize_spm_selection(
    country_id: str, selection: SPMSelection | dict | None
) -> dict | None:
    """Resolve request identity against the installed bundle's certification.

    Omitted settings retain legacy behavior only for the current pinned US
    bundle. Canonical bundles always resolve a hash and scenario before caching.
    """
    if country_id != "us":
        if selection is not None:
            raise SPMValidationError(
                "SPM_SETTINGS_UNSUPPORTED", "SPM settings are only available for the US"
            )
        return None

    try:
        chosen = SPMSelection.model_validate({} if selection is None else selection)
    except ValidationError as error:
        raise SPMValidationError("SPM_SETTINGS_INVALID", str(error)) from error

    bundle = _current_bundle()
    if not isinstance(bundle, dict):
        raise SPMValidationError(
            "SPM_CONFIGURATION_UNAVAILABLE", "The installed bundle manifest is invalid"
        )
    measurements = bundle.get("measurements")
    configured = measurements.get("spm") if isinstance(measurements, dict) else None
    if not isinstance(configured, dict):
        if _legacy_bundle(bundle):
            if selection is None:
                return None
            raise SPMValidationError(
                "SPM_SETTINGS_UNSUPPORTED",
                "This US model bundle does not support canonical SPM settings",
            )
        raise SPMValidationError(
            "SPM_CONFIGURATION_UNAVAILABLE",
            "The installed bundle has no certified SPM measurement configuration",
        )

    try:
        defaults = SPMSelection.model_validate(configured)
        if defaults.forecast_content_sha256 is None or defaults.scenario is None:
            raise ValueError("The bundle must pin the SPM artifact hash and scenario")
        simulation_type = importlib.import_module("policyengine_us").Simulation
        if not simulation_supports_spm(simulation_type):
            raise ValueError("The installed US model does not support canonical SPM")
        forecast = _selected_forecast(defaults.forecast_content_sha256)
    except (ImportError, ValueError, TypeError, OSError) as error:
        raise SPMValidationError("SPM_CONFIGURATION_UNAVAILABLE", str(error)) from error

    if chosen.forecast_content_sha256 not in (None, defaults.forecast_content_sha256):
        raise SPMValidationError(
            "SPM_SETTINGS_INVALID",
            "SPM selection does not match this bundle's artifact hash",
        )
    values = {name: getattr(defaults, name) for name in SPMSelection.model_fields}
    values.update(chosen.model_dump(exclude_unset=True))
    if (
        "geography_kind" in chosen.model_fields_set
        and chosen.geography_kind != defaults.geography_kind
    ):
        values["geography_id"] = chosen.geography_id
    values["forecast_content_sha256"] = defaults.forecast_content_sha256
    values["scenario"] = chosen.scenario or defaults.scenario
    try:
        resolved = SPMSelection.model_validate(values)
        # The artifact validates scenario/information date without household input.
        forecast.entry(
            forecast.years[0], scenario=resolved.scenario, as_of=resolved.as_of
        )
        if resolved.county_vintage != "2020":
            raise ValueError("Unsupported county vintage: use 2020")
    except ValueError as error:
        raise SPMValidationError("SPM_SETTINGS_INVALID", str(error)) from error
    if resolved.geography_kind == "metro":
        _validate_metro_selection(forecast, resolved)
    return resolved.model_dump(mode="json")


def _validate_metro_selection(forecast, selection: SPMSelection) -> None:
    """A selected area must exist in the artifact, without guessing a year.

    Area definitions may change between years. Accept an area available in any
    covered year; the country owns validation for the actual calculation year.
    This reads geography metadata and creates no household calculation receipt.
    """
    for year in forecast.years:
        try:
            forecast.geography_factor(
                year,
                "renter",
                scenario=selection.scenario,
                kind="metro",
                geoid=selection.geography_id,
                as_of=selection.as_of,
            )
        except ValueError:
            continue
        return
    raise SPMValidationError(
        "SPM_GEOGRAPHY_UNAVAILABLE",
        f"SPM area is unavailable in the selected artifact: {selection.geography_id}",
    )


def spm_metadata(country_id: str) -> dict:
    """Advertise an available selection only after the certified boundary passes."""
    if country_id != "us":
        return {"available": False}
    try:
        defaults = normalize_spm_selection(country_id, None)
    except SPMValidationError:
        return {"available": False}
    if defaults is None:
        return {"available": False}
    return {
        "available": True,
        "settings_schema": SPMSelection.model_json_schema(),
        "defaults": defaults,
    }


def calculation_spm_receipt(simulation) -> dict:
    """Read existing calculation receipts; never request SPM calculations here."""
    if not hasattr(simulation, "spm_config"):
        return {}
    return {
        "spm_config": SPMSelection.model_validate(simulation.spm_config).model_dump(
            mode="json"
        ),
        "spm_provenance": SPMProvenance.model_validate(
            simulation.spm_provenance()
        ).model_dump(mode="json"),
    }
