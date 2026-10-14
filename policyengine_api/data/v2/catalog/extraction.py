"""Normalize the installed PolicyEngine.py public model catalog."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from importlib import metadata as importlib_metadata
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from policyengine_api.data.v2.catalog.records import (
    CountryCatalog,
    DatasetRecord,
    FallbackSummary,
    ModelRecord,
    ModelVersionRecord,
    NormalizedCatalog,
    ParameterNodeRecord,
    ParameterRecord,
    ParameterValueRecord,
    RegionRecord,
    VariableRecord,
)

if TYPE_CHECKING:
    from policyengine_api.json_types import JSONValue

SUPPORTED_COUNTRIES = ("us", "uk")
REQUIRED_DEPENDENCIES = (
    "policyengine-core",
    "policyengine-us",
    "policyengine-uk",
)
REVIEWED_DEFAULT_DATASETS = {
    "us": "populace_us_2024",
    "uk": "enhanced_frs_2024_25",
}
CURRENT_LAW_IDS = {"us": 2, "uk": 1}
METADATA_TIME_PERIODS = {
    "us": tuple(range(2035, 2021, -1)),
    "uk": tuple(range(2024, 2031)),
}
SUPPORTED_REGION_TYPES = frozenset(
    {
        "national",
        "country",
        "state",
        "congressional_district",
        "constituency",
        "local_authority",
        "city",
        "place",
    }
)
PLACEHOLDER_VERSIONS = frozenset({"", "0", "0.0", "0.0.0", "unknown"})
DATASET_YEAR_PATTERN = re.compile(r"(?:19|20)\d{2}")


class CatalogExtractionError(RuntimeError):
    """Raised before database access when source metadata cannot be normalized."""


def _identifier(*parts: object) -> UUID:
    value = "/".join(str(part) for part in parts)
    return uuid5(NAMESPACE_URL, f"https://api.policyengine.org/v2/catalog/{value}")


def _required_text(value: object, *, field_name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        msg = f"{field_name} must be a non-empty string"
        raise CatalogExtractionError(msg)
    normalized = value.strip()
    if len(normalized) > maximum:
        msg = f"{field_name} exceeds {maximum} characters"
        raise CatalogExtractionError(msg)
    return normalized


def _optional_text(
    value: object,
    *,
    field_name: str,
    maximum: int | None = None,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"{field_name} must be a string or null"
        raise CatalogExtractionError(msg)
    if maximum is not None and len(value) > maximum:
        msg = f"{field_name} exceeds {maximum} characters"
        raise CatalogExtractionError(msg)
    return value


def _serialize_region_filter_value(value: object, *, region_code: str) -> str:
    """Keep scalar text or encode flat membership values in the existing column.

    Since PolicyEngine 6.2.7, the England filter names all nine English regions. The
    catalog's existing text column can retain that complete list as a JSON
    array without changing its schema or the representation of scalar filters.
    """
    scalar_types = (str, int, float, bool)
    if isinstance(value, scalar_types):
        serialized = str(value)
    elif (
        isinstance(value, (list, tuple))
        and value
        and all(isinstance(item, scalar_types) for item in value)
    ):
        try:
            serialized = json.dumps(
                value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            )
        except ValueError as error:
            msg = f"region {region_code!r} has an unsupported filter value"
            raise CatalogExtractionError(msg) from error
    else:
        msg = f"region {region_code!r} has an unsupported filter value"
        raise CatalogExtractionError(msg)
    if len(serialized) > 255:
        msg = f"region {region_code!r} filter value exceeds 255 characters"
        raise CatalogExtractionError(msg)
    return serialized


def _type_name(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    name = getattr(value, "__name__", None)
    if not isinstance(name, str) or not name:
        msg = f"unsupported data type {value!r}"
        raise CatalogExtractionError(msg)
    return name


def normalize_json_value(value: object) -> JSONValue:
    """Convert supported public values into strict JSON-compatible values."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            msg = "NaN is not JSON-compatible"
            raise CatalogExtractionError(msg)
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value
    if isinstance(value, Enum):
        return normalize_json_value(value.value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        normalized: dict[str, JSONValue] = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                msg = "JSON object keys must be strings"
                raise CatalogExtractionError(msg)
            normalized[key] = normalize_json_value(nested)
        return normalized
    if isinstance(value, (list, tuple)):
        return [normalize_json_value(item) for item in value]

    item = getattr(value, "item", None)
    if callable(item):
        scalar = item()
        if scalar is not value:
            return normalize_json_value(scalar)
    msg = f"unsupported JSON value type {type(value).__module__}.{type(value).__name__}"
    raise CatalogExtractionError(msg)


def _aware_datetime(value: object, *, field_name: str) -> datetime:
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime(value.year, value.month, value.day)
    if not isinstance(value, datetime):
        msg = f"{field_name} must be a date or datetime"
        raise CatalogExtractionError(msg)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_aware_datetime(value: object, *, field_name: str) -> datetime | None:
    if value is None:
        return None
    return _aware_datetime(value, field_name=field_name)


def _dataset_name_from_path(path: str) -> str:
    without_revision = path.split("@", maxsplit=1)[0]
    parsed_path = urlsplit(without_revision).path or without_revision
    filename = parsed_path.rstrip("/").rsplit("/", maxsplit=1)[-1]
    for suffix in (".hdf5", ".parquet", ".csv", ".h5"):
        if filename.endswith(suffix):
            filename = filename[: -len(suffix)]
            break
    return _required_text(filename, field_name="dataset name", maximum=255)


def _dataset_year(name: str) -> int:
    matches = DATASET_YEAR_PATTERN.findall(name)
    if not matches:
        msg = f"dataset {name!r} has no four-digit year"
        raise CatalogExtractionError(msg)
    match = list(DATASET_YEAR_PATTERN.finditer(name))[-1]
    return int(match.group())


def _verify_bundle(
    *,
    bundle: Mapping[str, Any],
    policyengine_version: str,
    installed_version: Callable[[str], str],
) -> tuple[tuple[str, str], ...]:
    if (
        not isinstance(policyengine_version, str)
        or policyengine_version.strip().lower() in PLACEHOLDER_VERSIONS
    ):
        msg = "PolicyEngine.py version is a placeholder"
        raise CatalogExtractionError(msg)
    canonical_version = _required_text(
        policyengine_version,
        field_name="PolicyEngine.py version",
        maximum=128,
    )
    manifest_version = bundle.get("policyengine_version") or bundle.get(
        "bundle_version"
    )
    if manifest_version != canonical_version:
        msg = "installed PolicyEngine.py version does not match its packaged manifest"
        raise CatalogExtractionError(msg)

    packages = bundle.get("packages")
    if not isinstance(packages, Mapping):
        msg = "PolicyEngine.py manifest has no package map"
        raise CatalogExtractionError(msg)

    observed_dependencies: list[tuple[str, str]] = []
    for package_name in REQUIRED_DEPENDENCIES:
        package = packages.get(package_name)
        if not isinstance(package, Mapping):
            msg = f"PolicyEngine.py manifest omits {package_name}"
            raise CatalogExtractionError(msg)
        expected = package.get("version")
        if not isinstance(expected, str) or expected.lower() in PLACEHOLDER_VERSIONS:
            msg = f"PolicyEngine.py manifest has no valid {package_name} version"
            raise CatalogExtractionError(msg)
        try:
            observed = installed_version(package_name)
        except importlib_metadata.PackageNotFoundError as error:
            msg = f"required installed distribution {package_name} is absent"
            raise CatalogExtractionError(msg) from error
        if observed != expected:
            msg = (
                f"installed {package_name} version does not match "
                "the PolicyEngine.py manifest"
            )
            raise CatalogExtractionError(msg)
        observed_dependencies.append((package_name, expected))
    return tuple(observed_dependencies)


def _normalize_variable(
    source: object,
    *,
    model_version_id: UUID,
) -> VariableRecord:
    name = _required_text(
        getattr(source, "name", None), field_name="variable name", maximum=512
    )
    possible_values = getattr(source, "possible_values", None)
    if possible_values is not None:
        if not isinstance(possible_values, Sequence) or isinstance(
            possible_values, (str, bytes)
        ):
            msg = f"variable {name!r} possible_values must be a sequence"
            raise CatalogExtractionError(msg)
        normalized_possible_values = [
            _required_text(
                value, field_name=f"variable {name} possible value", maximum=255
            )
            for value in possible_values
        ]
    else:
        normalized_possible_values = None

    def optional_names(attribute: str) -> list[str] | None:
        values = getattr(source, attribute, None)
        if values is None:
            return None
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            msg = f"variable {name!r} {attribute} must be a sequence"
            raise CatalogExtractionError(msg)
        return [
            _required_text(
                value,
                field_name=f"variable {name} {attribute} item",
                maximum=512,
            )
            for value in values
        ]

    return VariableRecord(
        id=_identifier("variable", model_version_id, name),
        model_version_id=model_version_id,
        name=name,
        label=_optional_text(
            getattr(source, "label", None),
            field_name=f"variable {name} label",
            maximum=512,
        ),
        entity=_required_text(
            getattr(source, "entity", None),
            field_name=f"variable {name} entity",
            maximum=128,
        ),
        description=_optional_text(
            getattr(source, "description", None),
            field_name=f"variable {name} description",
        ),
        data_type=_type_name(getattr(source, "data_type", None)),
        possible_values=normalized_possible_values,
        default_value=normalize_json_value(getattr(source, "default_value", None)),
        adds=optional_names("adds"),
        subtracts=optional_names("subtracts"),
    )


def _normalize_parameter(
    source: object,
    *,
    model_version_id: UUID,
) -> ParameterRecord:
    name = _required_text(
        getattr(source, "name", None),
        field_name="parameter name",
        maximum=512,
    )
    parameter_id = _identifier("parameter", model_version_id, name)
    source_values: list[tuple[datetime, datetime | None, Any]] = []
    values_by_start: dict[datetime, tuple[datetime | None, Any]] = {}
    previous_start: datetime | None = None
    for source_value in getattr(source, "parameter_values", ()):
        start_date = _aware_datetime(
            getattr(source_value, "start_date", None),
            field_name=f"parameter {name} value start_date",
        )
        end_date = _optional_aware_datetime(
            getattr(source_value, "end_date", None),
            field_name=f"parameter {name} value end_date",
        )
        try:
            value_json = normalize_json_value(getattr(source_value, "value", None))
        except CatalogExtractionError as error:
            msg = f"parameter {name!r} has an unsupported JSON value: {error}"
            raise CatalogExtractionError(msg) from error
        if start_date in values_by_start:
            previous_end, previous_value = values_by_start[start_date]
            if previous_value != value_json:
                msg = (
                    f"parameter {name!r} has conflicting values at effective "
                    f"date {start_date.isoformat()}"
                )
                raise CatalogExtractionError(msg)
            if previous_end != end_date:
                msg = (
                    f"parameter {name!r} exposes inconsistent intervals at effective "
                    f"date {start_date.isoformat()}"
                )
                raise CatalogExtractionError(msg)
            continue
        if previous_start is not None and start_date <= previous_start:
            msg = f"parameter {name!r} values are not ordered oldest to newest"
            raise CatalogExtractionError(msg)
        values_by_start[start_date] = (end_date, value_json)
        previous_start = start_date
        source_values.append((start_date, end_date, value_json))

    normalized_values: list[ParameterValueRecord] = []
    for index, (start_date, supplied_end, value_json) in enumerate(source_values):
        expected_end = (
            source_values[index + 1][0] - timedelta(days=1)
            if index + 1 < len(source_values)
            else None
        )
        if supplied_end != expected_end:
            msg = f"parameter {name!r} does not expose canonical inclusive intervals"
            raise CatalogExtractionError(msg)
        normalized_values.append(
            ParameterValueRecord(
                id=_identifier("parameter-value", parameter_id, start_date.isoformat()),
                parameter_id=parameter_id,
                value_json=value_json,
                start_date=start_date,
                end_date=expected_end,
            )
        )

    return ParameterRecord(
        id=parameter_id,
        model_version_id=model_version_id,
        name=name,
        label=_optional_text(
            getattr(source, "label", None),
            field_name=f"parameter {name} label",
            maximum=512,
        ),
        description=_optional_text(
            getattr(source, "description", None),
            field_name=f"parameter {name} description",
        ),
        data_type=_type_name(getattr(source, "data_type", None)),
        unit=_optional_text(
            getattr(source, "unit", None),
            field_name=f"parameter {name} unit",
            maximum=128,
        ),
        values=tuple(normalized_values),
    )


def _public_named_records(
    source: object,
    *,
    attribute: str,
    entity_name: str,
) -> tuple[object, ...]:
    records = getattr(source, attribute, None)
    if not isinstance(records, Mapping):
        msg = f"public model {attribute} must be a name-indexed mapping"
        raise CatalogExtractionError(msg)

    normalized: list[object] = []
    for key, record in sorted(records.items()):
        name = getattr(record, "name", None)
        if key != name:
            msg = (
                f"{entity_name} mapping key {key!r} does not match record name {name!r}"
            )
            raise CatalogExtractionError(msg)
        normalized.append(record)
    return tuple(normalized)


def _normalize_country(
    *,
    country_id: str,
    source: object,
    policyengine_version: str,
    expected_country_package_version: str,
) -> CountryCatalog:
    source_model = getattr(source, "model", None)
    expected_model_name = f"policyengine-{country_id}"
    model_name = _required_text(
        getattr(source_model, "id", None),
        field_name=f"{country_id} model name",
        maximum=32,
    )
    if model_name != expected_model_name:
        msg = f"{country_id} public model identity does not match {expected_model_name}"
        raise CatalogExtractionError(msg)
    model_id = _identifier("model", model_name)
    model_version_id = _identifier("model-version", model_id, policyengine_version)

    model_package = getattr(source, "model_package", None)
    if getattr(model_package, "name", None) != expected_model_name:
        msg = (
            f"{country_id} public model package identity does not match "
            f"{expected_model_name}"
        )
        raise CatalogExtractionError(msg)
    if getattr(model_package, "version", None) != expected_country_package_version:
        msg = f"{country_id} public model does not match the PolicyEngine.py manifest"
        raise CatalogExtractionError(msg)
    release_manifest = getattr(source, "release_manifest", None)
    if getattr(release_manifest, "country_id", None) != country_id:
        msg = f"{country_id} public model has an inconsistent release manifest"
        raise CatalogExtractionError(msg)
    if getattr(release_manifest, "policyengine_version", None) != policyengine_version:
        msg = (
            f"{country_id} public model was not certified by the installed "
            "PolicyEngine.py version"
        )
        raise CatalogExtractionError(msg)

    variables = tuple(
        _normalize_variable(variable, model_version_id=model_version_id)
        for variable in _public_named_records(
            source,
            attribute="variables_by_name",
            entity_name="variable",
        )
    )
    normalized_nodes: list[ParameterNodeRecord] = []
    for node in _public_named_records(
        source,
        attribute="parameter_nodes_by_name",
        entity_name="parameter node",
    ):
        source_name = getattr(node, "name", None)
        # The public UK model includes one unnamed structural root. It has no
        # addressable identity and contains no metadata of its own.
        if source_name == "":
            continue
        node_name = _required_text(
            source_name,
            field_name="parameter node name",
            maximum=512,
        )
        normalized_nodes.append(
            ParameterNodeRecord(
                id=_identifier("parameter-node", model_version_id, node_name),
                model_version_id=model_version_id,
                name=node_name,
                label=_optional_text(
                    getattr(node, "label", None),
                    field_name="parameter node label",
                    maximum=512,
                ),
                description=_optional_text(
                    getattr(node, "description", None),
                    field_name="parameter node description",
                ),
            )
        )
    parameter_nodes = tuple(normalized_nodes)
    parameters = tuple(
        _normalize_parameter(parameter, model_version_id=model_version_id)
        for parameter in _public_named_records(
            source,
            attribute="parameters_by_name",
            entity_name="parameter",
        )
    )

    reviewed_default = REVIEWED_DEFAULT_DATASETS[country_id]
    manifest_default = getattr(release_manifest, "default_dataset", None)
    if manifest_default != reviewed_default:
        msg = f"{country_id} default dataset does not match the reviewed selection"
        raise CatalogExtractionError(msg)
    default_dataset_uri = getattr(release_manifest, "default_dataset_uri", None)
    registry = getattr(source, "region_registry", None)
    if registry is None or getattr(registry, "country_id", None) != country_id:
        msg = f"{country_id} public region registry is absent"
        raise CatalogExtractionError(msg)

    source_regions = tuple(registry)
    region_codes = [getattr(region, "code", None) for region in source_regions]
    duplicate_region_codes = sorted(
        code for code, count in Counter(region_codes).items() if count > 1
    )
    if duplicate_region_codes:
        msg = f"duplicate region natural keys: {duplicate_region_codes[:3]}"
        raise CatalogExtractionError(msg)
    if country_id not in region_codes:
        msg = f"{country_id} national region is absent"
        raise CatalogExtractionError(msg)

    selected_dataset_names: set[str] = {reviewed_default}
    region_dataset_names: dict[str, str] = {}
    fallback_counts: Counter[str] = Counter()
    for region in source_regions:
        code = _required_text(
            getattr(region, "code", None),
            field_name="region code",
            maximum=255,
        )
        region_type = _required_text(
            getattr(region, "region_type", None),
            field_name=f"region {code} type",
            maximum=64,
        )
        if region_type not in SUPPORTED_REGION_TYPES:
            msg = f"region {code!r} has unsupported type {region_type!r}"
            raise CatalogExtractionError(msg)
        dataset_path = getattr(region, "dataset_path", None)
        if country_id == "us" and region_type != "national" and dataset_path:
            dataset_name = _dataset_name_from_path(dataset_path)
            selected_dataset_names.add(dataset_name)
        else:
            dataset_name = reviewed_default
            if country_id == "us" and region_type != "national" and not dataset_path:
                fallback_counts[region_type] += 1
        if region_type == "national" and dataset_path not in {
            None,
            default_dataset_uri,
        }:
            msg = f"{country_id} national region does not use the reviewed dataset"
            raise CatalogExtractionError(msg)
        region_dataset_names[code] = dataset_name

    datasets = tuple(
        DatasetRecord(
            id=_identifier("dataset", model_version_id, name),
            model_version_id=model_version_id,
            name=name,
            description=f"PolicyEngine.py logical input dataset {name}",
            year=_dataset_year(name),
        )
        for name in sorted(selected_dataset_names)
    )
    dataset_ids = {dataset.name: dataset.id for dataset in datasets}

    regions: list[RegionRecord] = []
    for source_region in source_regions:
        code = str(getattr(source_region, "code"))
        strategy = getattr(source_region, "scoping_strategy", None)
        requires_filter = bool(getattr(source_region, "requires_filter", False))
        if requires_filter:
            strategy_type = _required_text(
                getattr(strategy, "strategy_type", None),
                field_name=f"region {code} filter strategy",
                maximum=64,
            )
            filter_field = _required_text(
                getattr(strategy, "variable_name", None),
                field_name=f"region {code} filter field",
                maximum=128,
            )
            filter_value_source = getattr(strategy, "variable_value", None)
            filter_value = _serialize_region_filter_value(
                filter_value_source, region_code=code
            )
            additional_filters = getattr(strategy, "additional_filters", {})
            if additional_filters:
                msg = f"region {code!r} has unsupported additional filters"
                raise CatalogExtractionError(msg)
        else:
            strategy_type = None
            filter_field = None
            filter_value = None

        regions.append(
            RegionRecord(
                id=_identifier("region", model_version_id, code),
                model_version_id=model_version_id,
                default_dataset_id=dataset_ids[region_dataset_names[code]],
                code=code,
                label=_required_text(
                    getattr(source_region, "label", None),
                    field_name=f"region {code} label",
                    maximum=255,
                ),
                region_type=str(getattr(source_region, "region_type")),
                requires_filter=requires_filter,
                filter_field=filter_field,
                filter_value=filter_value,
                filter_strategy=strategy_type,
                parent_code=_optional_text(
                    getattr(source_region, "parent_code", None),
                    field_name=f"region {code} parent_code",
                    maximum=255,
                ),
                state_code=_optional_text(
                    getattr(source_region, "state_code", None),
                    field_name=f"region {code} state_code",
                    maximum=16,
                ),
                state_name=_optional_text(
                    getattr(source_region, "state_name", None),
                    field_name=f"region {code} state_name",
                    maximum=128,
                ),
            )
        )

    return CountryCatalog(
        country_id=country_id,
        model=ModelRecord(
            id=model_id,
            country_id=country_id,
            name=model_name,
            description=_optional_text(
                getattr(source_model, "description", None),
                field_name=f"{country_id} model description",
            ),
        ),
        model_version=ModelVersionRecord(
            id=model_version_id,
            model_id=model_id,
            version=policyengine_version,
            description=_optional_text(
                getattr(source_model, "description", None),
                field_name=f"{country_id} model-version description",
            ),
            current_law_id=CURRENT_LAW_IDS[country_id],
            metadata_time_periods=METADATA_TIME_PERIODS[country_id],
        ),
        variables=variables,
        parameter_nodes=parameter_nodes,
        parameters=parameters,
        datasets=datasets,
        regions=tuple(sorted(regions, key=lambda record: record.code)),
        fallback_summaries=tuple(
            FallbackSummary(region_type=region_type, count=count)
            for region_type, count in sorted(fallback_counts.items())
        ),
    )


def extract_catalog(
    *,
    bundle: Mapping[str, Any],
    policyengine_version: str,
    models: Mapping[str, object],
    installed_version: Callable[[str], str] = importlib_metadata.version,
) -> NormalizedCatalog:
    """Validate and normalize supplied PolicyEngine.py public objects."""
    dependencies = _verify_bundle(
        bundle=bundle,
        policyengine_version=policyengine_version,
        installed_version=installed_version,
    )
    missing = [country for country in SUPPORTED_COUNTRIES if country not in models]
    if missing:
        msg = f"PolicyEngine.py public models are absent for: {', '.join(missing)}"
        raise CatalogExtractionError(msg)

    package_map = bundle["packages"]
    countries = tuple(
        _normalize_country(
            country_id=country_id,
            source=models[country_id],
            policyengine_version=policyengine_version,
            expected_country_package_version=package_map[f"policyengine-{country_id}"][
                "version"
            ],
        )
        for country_id in SUPPORTED_COUNTRIES
    )
    return NormalizedCatalog(
        policyengine_version=policyengine_version,
        dependency_versions=dependencies,
        countries=countries,
    )


def extract_installed_catalog() -> NormalizedCatalog:
    """Load and normalize the installed PolicyEngine.py certified catalog."""
    import policyengine
    from policyengine.bundle import get_current_bundle

    policyengine_version = importlib_metadata.version("policyengine")
    return extract_catalog(
        bundle=get_current_bundle(),
        policyengine_version=policyengine_version,
        models={
            "us": policyengine.us.model,
            "uk": policyengine.uk.model,
        },
    )
