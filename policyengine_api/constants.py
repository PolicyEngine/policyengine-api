"""API version, country package versions and bundle metadata, resolved at import.

Also reads the UK area lists packaged with .py.
"""

import csv
import hashlib
import io
import json
from datetime import datetime
from importlib.metadata import distribution, distributions
from pathlib import Path
from typing import Any, Literal

from policyengine_api.dataset_display import (
    DEFAULT_DATASET_DISPLAY_LABEL,
    get_dataset_display_label,
)

REPO = Path(__file__).parents[1]
GET = "GET"
POST = "POST"
UPDATE = "UPDATE"
LIST = "LIST"
VERSION = "3.38.1"
CURRENT_YEAR = str(datetime.now().year)  # noqa: DTZ005  # the default year is the host's local calendar year
COUNTRIES = ("uk", "us", "ca", "ng", "il")
COUNTRY_PACKAGE_NAMES = (
    "policyengine_uk",
    "policyengine_us",
    "policyengine_canada",
    "policyengine_ng",
    "policyengine_il",
)
BUNDLED_COUNTRY_PACKAGE_NAMES = {
    "uk": "policyengine-uk",
    "us": "policyengine-us",
}
DEFAULT_BUNDLE_DATASET_LABEL = DEFAULT_DATASET_DISPLAY_LABEL


def _normalize_distribution_name(name: str | None) -> str:
    if name is None:
        return ""
    return name.replace("_", "-").lower()


def _resolve_distribution_version(
    dist_versions: dict[str, str], *package_names: str
) -> str:
    for package_name in package_names:
        version = dist_versions.get(_normalize_distribution_name(package_name))
        if version is not None:
            return version
    return "0.0.0"


def get_py_manifest() -> Any:  # noqa: ANN401  # SimplePath, which open() rejects; a Path at runtime
    """Return the path of the bundle manifest in the installed policyengine wheel."""
    return distribution("policyengine").locate_file(
        "policyengine/data/bundle/manifest.json"
    )


UKAreaType = Literal["constituency", "local_authority"]
PY_UK_AREA_LIST_FILES: dict[UKAreaType, str] = {
    "constituency": "policyengine/data/uk_geography/constituencies_2024.csv",
    "local_authority": "policyengine/data/uk_geography/local_authorities_2023.csv",
}


def get_py_uk_area_names(area_type: UKAreaType) -> list[str]:
    """Return the area names in .py's packaged list for a UK area type, in file order.

    .py builds its UK region registry from these files. They are read from the
    installed policyengine wheel rather than through .py, because importing
    any .py module builds .py's country models, which takes several seconds
    and requests release manifests over the network.
    """
    area_list = distribution("policyengine").locate_file(
        PY_UK_AREA_LIST_FILES[area_type]
    )
    rows = csv.DictReader(io.StringIO(area_list.read_text(encoding="utf-8")))
    return [row["name"] for row in rows]


def _load_policyengine_bundle() -> dict | None:
    try:
        with Path(get_py_manifest()).open() as manifest_file:
            manifest = json.load(manifest_file)
    except Exception as exc:
        msg = (
            "Could not read PolicyEngine .py bundle manifest from the installed "
            "policyengine wheel."
        )
        raise RuntimeError(msg) from exc
    if not isinstance(manifest, dict):
        msg = "PolicyEngine .py bundle manifest must be a JSON object."
        raise TypeError(msg)
    return manifest


def _resolve_bundle_package_versions(bundle: dict | None) -> dict[str, str]:
    if not isinstance(bundle, dict):
        return {}

    packages = bundle.get("packages")
    if not isinstance(packages, dict):
        return {}

    package_versions: dict[str, str] = {}
    for package_key, package in packages.items():
        if not isinstance(package, dict):
            continue
        version = package.get("version")
        if version is None:
            continue
        name = package.get("name") or package_key
        package_versions[_normalize_distribution_name(str(name))] = str(version)
    return package_versions


def get_bundle_manifest() -> dict | None:
    """Return the installed bundle manifest read at import, or None if it is missing."""
    return _policyengine_bundle


def get_bundle_data_release(country_id: str) -> dict:
    """Return the bundle's data release entry for a country, or {} if it has none."""
    if not isinstance(_policyengine_bundle, dict):
        return {}

    data_releases = _policyengine_bundle.get("data_releases")
    if not isinstance(data_releases, dict):
        return {}

    release = data_releases.get(country_id)
    if not isinstance(release, dict):
        return {}

    return release


def get_bundle_default_dataset(country_id: str) -> str | None:
    """Return the bundle's default dataset name for a country, or None if unset."""
    release = get_bundle_data_release(country_id)
    default_dataset = release.get("default_dataset")
    if default_dataset is None:
        return None
    return str(default_dataset)


def _bundle_dataset_display_label(default_dataset: object) -> str:
    return get_dataset_display_label(default_dataset)


def get_bundle_default_dataset_option(country_id: str) -> dict:
    """Build the metadata dataset option for the bundle's certified default dataset.

    The option carries ``dataset_uri`` and ``data_version`` only when the bundle
    records them.
    """
    release = get_bundle_data_release(country_id)
    default_dataset = release.get("default_dataset")
    label = _bundle_dataset_display_label(default_dataset)
    title = (
        f"Certified {label} dataset"
        if label != DEFAULT_BUNDLE_DATASET_LABEL
        else DEFAULT_BUNDLE_DATASET_LABEL
    )

    option = {
        "name": str(default_dataset or "default"),
        "label": label,
        "title": title,
        "default": True,
    }

    default_dataset_uri = release.get("default_dataset_uri")
    if default_dataset_uri is not None:
        option["dataset_uri"] = str(default_dataset_uri)

    data_version = release.get("version") or release.get("build_id")
    if data_version is not None:
        option["data_version"] = str(data_version)

    return option


try:
    _dist_versions = {
        _normalize_distribution_name(d.metadata["Name"]): d.version
        for d in distributions()
    }
    COUNTRY_PACKAGE_VERSIONS = {
        country: _resolve_distribution_version(_dist_versions, package_name)
        for country, package_name in zip(COUNTRIES, COUNTRY_PACKAGE_NAMES, strict=True)
    }
except Exception:  # noqa: BLE001  # unreadable package metadata falls back to 0.0.0; import must not fail
    _dist_versions = {}
    COUNTRY_PACKAGE_VERSIONS = dict.fromkeys(COUNTRIES, "0.0.0")

_policyengine_bundle = _load_policyengine_bundle()
_bundle_package_versions = _resolve_bundle_package_versions(_policyengine_bundle)

for country, package_name in BUNDLED_COUNTRY_PACKAGE_NAMES.items():
    version = _bundle_package_versions.get(_normalize_distribution_name(package_name))
    if version is not None:
        COUNTRY_PACKAGE_VERSIONS[country] = version

POLICYENGINE_VERSION = _resolve_distribution_version(_dist_versions, "policyengine")
if isinstance(_policyengine_bundle, dict):
    bundle_version = _policyengine_bundle.get(
        "policyengine_version"
    ) or _policyengine_bundle.get("bundle_version")
    if bundle_version is not None:
        POLICYENGINE_VERSION = str(bundle_version)

POLICYENGINE_CORE_VERSION = _bundle_package_versions.get(
    "policyengine-core"
) or _resolve_distribution_version(_dist_versions, "policyengine-core", "policyengine")

RUNTIME_CACHE_SCHEMA_VERSIONS = {
    # 4: economy results cached under 3 can hold decile.relative and the UK
    # wealth_decile.relative as percentages (x100) instead of fractions, from
    # the simulation API (PolicyEngine/policyengine-sim-api#827). Economy cache
    # keys do not change when only the simulation API's code changes, so this
    # version was raised to stop serving those results. The budget-window
    # cache key uses the same version.
    "economy_impact": 4,
    "report_output": 3,
}
# Runtime cache versions are stored in legacy VARCHAR(10) columns, and keep at
# least this many digest characters after their scope prefix and schema version.
RUNTIME_CACHE_VERSION_LENGTH = 10
MINIMUM_RUNTIME_CACHE_DIGEST_LENGTH = 4


def _build_runtime_cache_version(
    scope: str, country_id: str, caller_version: str | None = None
) -> str:
    """Build a compact cache version token that fits legacy VARCHAR(10) columns.

    The token changes whenever the relevant runtime or payload schema changes,
    even if the country package version is unchanged.
    """
    schema_version = str(RUNTIME_CACHE_SCHEMA_VERSIONS[scope])
    prefix = "e" if scope == "economy_impact" else "r"
    digest_length = RUNTIME_CACHE_VERSION_LENGTH - len(prefix) - len(schema_version)
    if digest_length < MINIMUM_RUNTIME_CACHE_DIGEST_LENGTH:
        msg = f"Runtime cache version for {scope} does not fit in VARCHAR(10)"
        raise ValueError(msg)

    raw = "|".join(
        (
            scope,
            country_id,
            caller_version or COUNTRY_PACKAGE_VERSIONS.get(country_id, "0.0.0"),
            COUNTRY_PACKAGE_VERSIONS.get(country_id, "0.0.0"),
            POLICYENGINE_VERSION,
            POLICYENGINE_CORE_VERSION,
            schema_version,
        )
    )
    digest = hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"{prefix}{schema_version}{digest[:digest_length]}"


def get_economy_impact_cache_version(
    country_id: str, caller_version: str | None = None
) -> str:
    """Return the cache version stored with economy impacts for this country.

    ``caller_version`` is the country model version the request asked for; it
    defaults to the installed country package version.
    """
    return _build_runtime_cache_version("economy_impact", country_id, caller_version)


def get_report_output_cache_version(country_id: str) -> str:
    """Return the cache version that marks a report output current for this runtime."""
    return _build_runtime_cache_version("report_output", country_id)


# Valid region types for each country
# These define the geographic scope categories for regions
US_REGION_TYPES = (
    "national",  # National level (e.g., "us")
    "state",  # US states (e.g., "state/ca", "state/ny")
    "place",  # US Census places (e.g., "place/NJ-57000")
    # US congressional districts (e.g., "congressional_district/CA-37")
    "congressional_district",
)

UK_REGION_TYPES = (
    "national",  # National level (e.g., "uk")
    "country",  # UK countries (e.g., "country/england", "country/scotland")
    # UK parliamentary constituencies (e.g., "constituency/Aldershot")
    "constituency",
    "local_authority",  # UK local authorities (e.g., "local_authority/Maidstone")
)

# Valid region prefixes for each country
# These define the allowed geographic scope prefixes in region names
REGION_PREFIXES = {
    "us": [
        "state/",  # US states (e.g., "state/ca", "state/ny")
        "place/",  # US Census places (e.g., "place/NJ-57000")
        # US congressional districts (e.g., "congressional_district/CA-37")
        "congressional_district/",
    ],
    "uk": [
        "country/",  # UK countries (e.g., "country/england", "country/scotland")
        # UK parliamentary constituencies (e.g., "constituency/Aldershot")
        "constituency/",
        "local_authority/",  # UK local authorities (e.g., "local_authority/Maidstone")
    ],
}

# The UK country regions the metadata publishes, as (region name, label).
UK_COUNTRY_REGIONS = (
    ("country/england", "England"),
    ("country/scotland", "Scotland"),
    ("country/wales", "Wales"),
    ("country/ni", "Northern Ireland"),
)
# UK regions whose metadata name differs from the code .py's UK region
# registry uses, mapped to that code.
UK_REGION_REGISTRY_CODES = {"country/ni": "country/northern_ireland"}
# The regions a UK local-area breakdown can cover, in the order messages and
# the query description list them: the UK, each UK country the metadata
# publishes, and .py's own code for a country the metadata names differently.
LOCAL_AREA_BREAKDOWN_REGIONS = (
    "uk",
    *(name for name, _label in UK_COUNTRY_REGIONS),
    *UK_REGION_REGISTRY_CODES.values(),
)

# Modal simulation API status values
MODAL_EXECUTION_STATUS_SUBMITTED = "submitted"
MODAL_EXECUTION_STATUS_RUNNING = "running"
MODAL_EXECUTION_STATUS_COMPLETE = "complete"
MODAL_EXECUTION_STATUS_FAILED = "failed"

# Status groupings for EconomyService._handle_execution_state()
EXECUTION_STATUSES_SUCCESS = (MODAL_EXECUTION_STATUS_COMPLETE,)
EXECUTION_STATUSES_FAILURE = (MODAL_EXECUTION_STATUS_FAILED,)
EXECUTION_STATUSES_PENDING = (
    MODAL_EXECUTION_STATUS_SUBMITTED,
    MODAL_EXECUTION_STATUS_RUNNING,
)

__version__ = VERSION
