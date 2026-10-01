"""Public SPM settings and the certified US bundle boundary.

Household geography and composition are checked by the country only when an
SPM dependency is calculated. Resolving these settings never calculates one.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Mapping, Sequence
from functools import lru_cache
from datetime import date
from typing import Literal

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
    """Compact public receipt for one canonical SPM execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["canonical-spm-provenance-v2"]
    forecast_id: str = Field(min_length=1, pattern=r"^\S+$")
    forecast_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario: str = Field(min_length=1, pattern=r"^\S+$")
    geography_kind: Literal["county", "national", "metro"]
    geography_id: str | None = Field(min_length=1)
    county_vintage: str = Field(pattern=r"^[0-9]{4}$")
    as_of: date | None
    years: tuple[str, ...]
    runtime_versions: "SPMRuntimeVersions"

    @field_validator("years")
    @classmethod
    def validate_years(cls, years: tuple[str, ...]) -> tuple[str, ...]:
        if any(
            len(year) != 4 or not year.isascii() or not year.isdigit() for year in years
        ):
            raise ValueError("years must contain four-digit calendar years")
        if tuple(sorted(set(years))) != years:
            raise ValueError("years must be sorted and unique")
        return years

    @model_validator(mode="after")
    def validate_location(self) -> "SPMProvenance":
        if self.geography_kind == "metro":
            if self.geography_id is None or not self.geography_id.strip():
                raise ValueError("A metro SPM receipt requires geography_id")
        elif self.geography_id is not None:
            raise ValueError("Only a metro SPM receipt accepts geography_id")
        return self


class SPMRuntimeVersions(BaseModel):
    """Package versions required to reproduce one certified SPM execution."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)
    policyengine: str | None
    policyengine_core: str | None = Field(alias="policyengine-core")
    policyengine_us: str | None = Field(alias="policyengine-us")
    spm_calculator: str | None = Field(alias="spm-calculator")


SPMProvenance.model_rebuild()


class SPMCalculationProvenance(BaseModel):
    """A resolved SPM configuration and its matching compact receipt."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    spm_config: SPMSelection
    spm_provenance: SPMProvenance

    @model_validator(mode="after")
    def validate_matching_receipt(self) -> "SPMCalculationProvenance":
        receipt = self.spm_provenance
        config = self.spm_config
        receipt_as_of = receipt.as_of.isoformat() if receipt.as_of is not None else None
        if (
            receipt.forecast_sha256 != config.forecast_content_sha256
            or receipt.scenario != config.scenario
            or receipt.geography_kind != config.geography_kind
            or receipt.geography_id != config.geography_id
            or receipt.county_vintage != config.county_vintage
            or receipt_as_of != config.as_of
        ):
            raise ValueError("SPM receipt differs from the SPM configuration")
        return self


class SPMExecutionProvenance(BaseModel):
    """One shared compact receipt and the executions that produced it."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    receipt: SPMProvenance
    execution_count: int = Field(ge=1)


class SPMComparisonProvenance(BaseModel):
    """Compact baseline and reform receipts for a society-wide result."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["canonical-spm-comparison-v2"]
    baseline: SPMExecutionProvenance
    reform: SPMExecutionProvenance

    @model_validator(mode="after")
    def validate_compatible_receipts(self) -> "SPMComparisonProvenance":
        if self.baseline.receipt != self.reform.receipt:
            raise ValueError("baseline and reform SPM receipts differ")
        return self


def build_spm_provenance(
    *,
    forecast_id: str,
    forecast_sha256: str,
    selection: SPMSelection,
    years: Sequence[str],
    runtime_versions: SPMRuntimeVersions,
) -> SPMProvenance:
    """Build one compact receipt from typed calculation inputs."""

    if selection.forecast_content_sha256 != forecast_sha256:
        raise ValueError("SPM receipt differs from the SPM configuration")
    if selection.scenario is None:
        raise ValueError("Resolved SPM configuration must include scenario")
    return SPMProvenance(
        schema_version="canonical-spm-provenance-v2",
        forecast_id=forecast_id,
        forecast_sha256=forecast_sha256,
        scenario=selection.scenario,
        geography_kind=selection.geography_kind,
        geography_id=selection.geography_id,
        county_vintage=selection.county_vintage,
        as_of=selection.as_of,
        years=tuple(years),
        runtime_versions=runtime_versions,
    )


def _required_string(source: Mapping[str, object], field: str) -> str:
    value = source.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Country SPM receipt requires {field}")
    return value


def build_spm_calculation_provenance(
    config: SPMSelection,
    receipt: Mapping[str, object],
) -> SPMCalculationProvenance:
    """Reduce the country-owned rich receipt to the public compact contract."""

    forecast_sha256 = _required_string(receipt, "forecast_sha256")
    scenario = _required_string(receipt, "scenario")
    geography_kind = _required_string(receipt, "geography_kind")
    if (
        forecast_sha256 != config.forecast_content_sha256
        or scenario != config.scenario
        or geography_kind != config.geography_kind
    ):
        raise ValueError("Country SPM receipt differs from the SPM configuration")

    source_years = receipt.get("years")
    if not isinstance(source_years, Mapping):
        raise ValueError("Country SPM receipt requires a years mapping")
    years: list[str] = []
    for year in source_years:
        if not isinstance(year, str):
            raise ValueError("Country SPM receipt years must be strings")
        years.append(year)

    source_versions = receipt.get("runtime_versions")
    if not isinstance(source_versions, Mapping):
        raise ValueError("Country SPM receipt requires runtime_versions")
    runtime_versions = SPMRuntimeVersions.model_validate(source_versions)
    if any(
        version is None
        for version in (
            runtime_versions.policyengine,
            runtime_versions.policyengine_core,
            runtime_versions.policyengine_us,
            runtime_versions.spm_calculator,
        )
    ):
        raise ValueError("Certified SPM receipts require every runtime version")

    compact = build_spm_provenance(
        forecast_id=_required_string(receipt, "forecast_id"),
        forecast_sha256=forecast_sha256,
        selection=config,
        years=tuple(sorted(years)),
        runtime_versions=runtime_versions,
    )
    return SPMCalculationProvenance(
        spm_config=config,
        spm_provenance=compact,
    )


def _collapse_execution_receipts(
    side: Literal["baseline", "reform"],
    receipts: Sequence[SPMProvenance],
) -> SPMExecutionProvenance:
    if not receipts:
        raise ValueError(f"{side} SPM receipts are empty")
    first = receipts[0]
    if any(receipt != first for receipt in receipts[1:]):
        raise ValueError(f"{side} SPM receipts differ")
    return SPMExecutionProvenance(receipt=first, execution_count=len(receipts))


def build_spm_comparison_provenance(
    *,
    baseline_receipts: Sequence[SPMProvenance],
    reform_receipts: Sequence[SPMProvenance],
) -> SPMComparisonProvenance:
    """Collapse matching child receipts into one comparison receipt."""

    return SPMComparisonProvenance(
        schema_version="canonical-spm-comparison-v2",
        baseline=_collapse_execution_receipts("baseline", baseline_receipts),
        reform=_collapse_execution_receipts("reform", reform_receipts),
    )


class SPMValidationError(ValueError):
    """An SPM request/configuration error safe for the API's 4xx envelope."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def readable_validation_error(error: ValidationError) -> str:
    """Render pydantic's report as an API message.

    `str(ValidationError)` carries a version-pinned pydantic documentation URL
    and echoes the offending input back. Neither belongs in a message a client
    displays to its own users, and the URL invites them to read our validator's
    internals as their own contract.
    """
    return "; ".join(
        ": ".join(
            part
            for part in (
                ".".join(str(item) for item in detail["loc"]),
                detail["msg"].removeprefix("Value error, "),
            )
            if part
        )
        for detail in error.errors()
    )


def error_message(error: BaseException) -> str:
    """Render any SPM failure as an API message, never as validator internals.

    Settings arrive from a caller, a bundle manifest, a worker capability and a
    country receipt, and every one of those is validated by the same models. A
    message a client displays to its own users must read the same whichever of
    them failed.
    """
    if isinstance(error, ValidationError):
        return readable_validation_error(error)
    return str(error)


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


# A transported resolved selection freezes all six fields, including explicit
# null values. Receipt validation never fills output from current defaults.
REQUIRED_RESOLVED_SPM_FIELDS = frozenset(SPMSelection.model_fields)


def resolved_spm_settings(settings: object) -> dict | None:
    """Expand receipt settings to every resolved field, or None if unusable.

    Returns None when the settings are unreadable or omit a field whose value
    cannot be recovered, so no caller ever compares a receipt against today's
    defaults. Every consumer of a receipt's settings shares this one rule.
    """
    try:
        config = SPMSelection.model_validate(settings)
    except ValidationError:
        return None
    if not REQUIRED_RESOLVED_SPM_FIELDS <= config.model_fields_set:
        return None
    return {name: getattr(config, name) for name in SPMSelection.model_fields}


def validate_spm_calculation_provenance(
    config: object,
    provenance: object,
) -> SPMCalculationProvenance:
    """Validate a transported compact receipt against its resolved selection."""

    resolved = resolved_spm_settings(config)
    if resolved is None:
        raise ValueError("SPM configuration is incomplete")
    return SPMCalculationProvenance(
        spm_config=SPMSelection.model_validate(resolved),
        spm_provenance=SPMProvenance.model_validate(provenance),
    )


def _current_bundle() -> dict:
    from policyengine_api.constants import _policyengine_bundle

    return _policyengine_bundle


def _installed_country_implements_spm(country_id: str) -> bool:
    """Whether the installed country model implements the canonical constructor.

    Version strings move for reasons that have nothing to do with SPM — a wrapper
    release for another country, a patch bump — so they cannot decide whether a
    bundle predates this contract, and keying on them makes an unrelated bundle
    bump reject every request. Constructor support can decide it: a model without
    it computes SPM exactly as it always has, and a model with it still needs a
    certified configuration before this API will run it.
    """
    from policyengine_api.constants import COUNTRIES, COUNTRY_PACKAGE_NAMES

    package_name = dict(zip(COUNTRIES, COUNTRY_PACKAGE_NAMES)).get(country_id)
    if package_name is None:
        return False
    try:
        simulation_type = importlib.import_module(package_name).Simulation
    except (AttributeError, ImportError, OSError, TypeError, ValueError):
        # A model this build cannot load is a model without the canonical
        # constructor, whatever stopped the import: a missing distribution, a
        # package without a Simulation, an extension that will not initialize.
        # Reading one of those as an internal failure would turn every US
        # request on an uncertified bundle into a 500 rather than the legacy
        # behaviour the bundle actually has. A certified bundle never reaches
        # this probe and still fails closed through its own import below.
        return False
    try:
        return simulation_supports_spm(simulation_type)
    except (TypeError, ValueError):
        return False


@lru_cache(maxsize=4)
def _selected_forecast(expected_sha256: str):
    from spm_calculator.rolling_forecast import load_forecast

    return load_forecast(expected_sha256=expected_sha256)


def normalize_spm_selection(
    country_id: str,
    selection: SPMSelection | dict | None,
    *,
    stored: bool = False,
) -> dict | None:
    """Resolve request identity against the installed bundle's certification.

    Omitted settings retain legacy behavior for any bundle whose installed US
    model lacks the canonical constructor, whatever the manifest calls itself. A
    certified bundle always resolves a hash and scenario before caching.

    `stored` says the selection was read back from storage rather than sent by
    this caller, which changes only how a hash that no longer matches the
    installed artifact is reported. Nothing else about the resolution differs.
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
        raise SPMValidationError(
            "SPM_SETTINGS_INVALID", readable_validation_error(error)
        ) from error

    bundle = _current_bundle()
    if not isinstance(bundle, dict):
        raise SPMValidationError(
            "SPM_CONFIGURATION_UNAVAILABLE", "The installed bundle manifest is invalid"
        )
    measurements = bundle.get("measurements")
    configured = measurements.get("spm") if isinstance(measurements, dict) else None
    if not isinstance(configured, dict):
        if _installed_country_implements_spm(country_id):
            # A model that can run canonical SPM must never run it uncertified,
            # whichever settings the caller did or did not send.
            raise SPMValidationError(
                "SPM_CONFIGURATION_UNAVAILABLE",
                "The installed bundle has no certified SPM measurement configuration",
            )
        if selection is None:
            return None
        raise SPMValidationError(
            "SPM_SETTINGS_UNSUPPORTED",
            "This US model bundle does not support canonical SPM settings",
        )

    try:
        defaults = SPMSelection.model_validate(configured)
        if defaults.forecast_content_sha256 is None or defaults.scenario is None:
            raise ValueError("The bundle must pin the SPM artifact hash and scenario")
        simulation_type = importlib.import_module("policyengine_us").Simulation
        if not simulation_supports_spm(simulation_type):
            raise ValueError("The installed US model does not support canonical SPM")
        forecast = _selected_forecast(defaults.forecast_content_sha256)
    except (AttributeError, ImportError, ValueError, TypeError, OSError) as error:
        # A country package installed without its Simulation raises AttributeError
        # here. The capability probe already reads that as "no canonical model";
        # letting it escape instead would make /readiness-check raise rather than
        # report not-ready, and every US request a 500 rather than a typed 400.
        raise SPMValidationError(
            "SPM_CONFIGURATION_UNAVAILABLE", error_message(error)
        ) from error

    if chosen.forecast_content_sha256 not in (None, defaults.forecast_content_sha256):
        # A saved selection is identity, not a request. The caller sent nothing
        # wrong; this deployment simply does not have the artifact the household
        # was measured against, which is the same class of failure as an
        # uncertified bundle rather than a correctable caller mistake.
        if stored:
            raise SPMValidationError(
                "SPM_CONFIGURATION_UNAVAILABLE",
                "This deployment does not have the SPM artifact this household's "
                "saved selection was measured against",
            )
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
        raise SPMValidationError(
            "SPM_SETTINGS_INVALID", error_message(error)
        ) from error
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
    """Reduce a country's existing receipt; never request calculations here."""
    if not hasattr(simulation, "spm_config"):
        return {}
    try:
        resolved = resolved_spm_settings(simulation.spm_config)
        if resolved is None:
            raise ValueError("Country SPM configuration is incomplete")
        source = simulation.spm_provenance()
        if not isinstance(source, Mapping):
            raise ValueError("Country SPM receipt must be an object")
        calculation = build_spm_calculation_provenance(
            SPMSelection.model_validate(resolved),
            source,
        )
        return calculation.model_dump(mode="json", by_alias=True)
    except (ValidationError, ValueError) as error:
        raise SPMValidationError(
            "SPM_CONFIGURATION_UNAVAILABLE",
            "The installed country model reported an SPM receipt this API cannot "
            f"certify: {error_message(error)}",
        ) from error
