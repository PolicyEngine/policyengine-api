"""Normalize a public model's regions and the logical input datasets they select."""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import TYPE_CHECKING, Any, NamedTuple, Protocol
from urllib.parse import urlsplit

from policyengine_api.data.v2.catalog.extraction_values import (
    CatalogExtractionError,
    catalog_identifier,
    optional_text,
    required_text,
)
from policyengine_api.data.v2.catalog.records import RegionRecord

if TYPE_CHECKING:
    from collections.abc import Mapping
    from uuid import UUID

REVIEWED_DEFAULT_DATASETS = {
    "us": "populace_us_2024",
    "uk": "microcosm_uk_2024_25",
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
DATASET_YEAR_PATTERN = re.compile(r"(?:19|20)\d{2}")


# The catalog's region filter_value column holds at most this many characters.
MAX_REGION_FILTER_VALUE_LENGTH = 255


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
    if len(serialized) > MAX_REGION_FILTER_VALUE_LENGTH:
        msg = (
            f"region {region_code!r} filter value exceeds "
            f"{MAX_REGION_FILTER_VALUE_LENGTH} characters"
        )
        raise CatalogExtractionError(msg)
    return serialized


def _dataset_name_from_path(path: str) -> str:
    without_revision = path.split("@", maxsplit=1)[0]
    parsed_path = urlsplit(without_revision).path or without_revision
    filename = parsed_path.rstrip("/").rsplit("/", maxsplit=1)[-1]
    for suffix in (".hdf5", ".parquet", ".csv", ".h5"):
        if filename.endswith(suffix):
            filename = filename[: -len(suffix)]
            break
    return required_text(filename, field_name="dataset name", maximum=255)


def dataset_year(name: str) -> int:
    """Return the last four-digit year in a dataset name; raise if it has none."""
    matches = DATASET_YEAR_PATTERN.findall(name)
    if not matches:
        msg = f"dataset {name!r} has no four-digit year"
        raise CatalogExtractionError(msg)
    match = list(DATASET_YEAR_PATTERN.finditer(name))[-1]
    return int(match.group())


class _RegionDatasetSelection(NamedTuple):
    """The logical input datasets a country's regions select.

    Names every selected dataset, each region code's dataset, and how many
    regions of each type fall back to the reviewed default dataset.
    """

    dataset_names: set[str]
    region_dataset_names: dict[str, str]
    fallback_counts: Counter[str]


def verified_default_dataset(
    country_id: str,
    release_manifest: object,
) -> tuple[str, object]:
    """Return the reviewed default dataset and the manifest's URI for it.

    The manifest's default dataset must be the reviewed one.
    """
    reviewed_default = REVIEWED_DEFAULT_DATASETS[country_id]
    manifest_default = getattr(release_manifest, "default_dataset", None)
    if manifest_default != reviewed_default:
        msg = f"{country_id} default dataset does not match the reviewed selection"
        raise CatalogExtractionError(msg)
    return reviewed_default, getattr(release_manifest, "default_dataset_uri", None)


def verified_source_regions(country_id: str, source: object) -> tuple[Any, ...]:
    """Return the country's public regions once their codes are unique and complete.

    The registry must belong to the country, and its codes must be unique and
    include the national region.
    """
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
    return source_regions


def select_region_datasets(
    country_id: str,
    source_regions: tuple[Any, ...],
    *,
    reviewed_default: str,
    default_dataset_uri: object,
) -> _RegionDatasetSelection:
    """Choose each region's logical input dataset.

    A subnational region with a dataset path uses that dataset: US states and
    districts, and the UK constituencies and local authorities that .py routes
    to its local-area release. Every other region, such as a UK country that
    filters the national file, uses the reviewed default, and the national
    region may only name it. A US subnational region without a path is
    counted as a fallback.
    """
    selected_dataset_names: set[str] = {reviewed_default}
    region_dataset_names: dict[str, str] = {}
    fallback_counts: Counter[str] = Counter()
    for region in source_regions:
        code = required_text(
            getattr(region, "code", None),
            field_name="region code",
            maximum=255,
        )
        region_type = required_text(
            getattr(region, "region_type", None),
            field_name=f"region {code} type",
            maximum=64,
        )
        if region_type not in SUPPORTED_REGION_TYPES:
            msg = f"region {code!r} has unsupported type {region_type!r}"
            raise CatalogExtractionError(msg)
        dataset_path = getattr(region, "dataset_path", None)
        if region_type != "national" and dataset_path:
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
    return _RegionDatasetSelection(
        dataset_names=selected_dataset_names,
        region_dataset_names=region_dataset_names,
        fallback_counts=fallback_counts,
    )


def _region_filter(strategy: object, code: str) -> tuple[str, str, str]:
    """Return a filtered region's strategy type, filter field and filter value."""
    strategy_type = required_text(
        getattr(strategy, "strategy_type", None),
        field_name=f"region {code} filter strategy",
        maximum=64,
    )
    filter_field = required_text(
        getattr(strategy, "variable_name", None),
        field_name=f"region {code} filter field",
        maximum=128,
    )
    filter_value = _serialize_region_filter_value(
        getattr(strategy, "variable_value", None), region_code=code
    )
    additional_filters = getattr(strategy, "additional_filters", {})
    if additional_filters:
        msg = f"region {code!r} has unsupported additional filters"
        raise CatalogExtractionError(msg)
    return strategy_type, filter_field, filter_value


class _SourceRegion(Protocol):
    """The attributes of a PolicyEngine.py region that normalize_region reads directly.

    It reads every other region attribute through getattr, with a default.
    """

    @property
    def code(self) -> object: ...

    @property
    def region_type(self) -> object: ...


def normalize_region(
    source_region: _SourceRegion,
    *,
    model_version_id: UUID,
    region_dataset_ids: Mapping[str, UUID],
) -> RegionRecord:
    """Normalize one public region, with its filter and default dataset."""
    code = str(source_region.code)
    strategy = getattr(source_region, "scoping_strategy", None)
    requires_filter = bool(getattr(source_region, "requires_filter", False))
    if requires_filter:
        strategy_type, filter_field, filter_value = _region_filter(strategy, code)
    else:
        strategy_type = None
        filter_field = None
        filter_value = None

    return RegionRecord(
        id=catalog_identifier("region", model_version_id, code),
        model_version_id=model_version_id,
        default_dataset_id=region_dataset_ids[code],
        code=code,
        label=required_text(
            getattr(source_region, "label", None),
            field_name=f"region {code} label",
            maximum=255,
        ),
        region_type=str(source_region.region_type),
        requires_filter=requires_filter,
        filter_field=filter_field,
        filter_value=filter_value,
        filter_strategy=strategy_type,
        parent_code=optional_text(
            getattr(source_region, "parent_code", None),
            field_name=f"region {code} parent_code",
            maximum=255,
        ),
        state_code=optional_text(
            getattr(source_region, "state_code", None),
            field_name=f"region {code} state_code",
            maximum=16,
        ),
        state_name=optional_text(
            getattr(source_region, "state_name", None),
            field_name=f"region {code} state_name",
            maximum=128,
        ),
    )
