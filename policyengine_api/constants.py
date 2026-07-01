import hashlib
import json
from datetime import datetime
from importlib.metadata import distribution, distributions
from pathlib import Path

REPO = Path(__file__).parents[1]
GET = "GET"
POST = "POST"
UPDATE = "UPDATE"
LIST = "LIST"
VERSION = "3.38.1"
CURRENT_YEAR = str(datetime.now().year)
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
BUNDLED_COUNTRY_DATASET_LABELS = {
    "populace": "Populace",
}
DEFAULT_BUNDLE_DATASET_LABEL = "Certified dataset"


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


def get_py_manifest():
    return distribution("policyengine").locate_file(
        "policyengine/data/bundle/manifest.json"
    )


def _load_policyengine_bundle() -> dict | None:
    try:
        with open(get_py_manifest()) as manifest_file:
            manifest = json.load(manifest_file)
    except Exception as exc:
        raise RuntimeError(
            "Could not read PolicyEngine .py bundle manifest from the installed "
            "policyengine wheel."
        ) from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("PolicyEngine .py bundle manifest must be a JSON object.")
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


def get_bundle_data_release(country_id: str) -> dict:
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
    release = get_bundle_data_release(country_id)
    default_dataset = release.get("default_dataset")
    if default_dataset is None:
        return None
    return str(default_dataset)


def get_bundle_default_dataset_option(country_id: str) -> dict:
    release = get_bundle_data_release(country_id)
    default_dataset = release.get("default_dataset")
    data_producer = release.get("data_producer")
    label = BUNDLED_COUNTRY_DATASET_LABELS.get(
        str(data_producer), DEFAULT_BUNDLE_DATASET_LABEL
    )
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
        for country, package_name in zip(COUNTRIES, COUNTRY_PACKAGE_NAMES)
    }
except Exception:
    _dist_versions = {}
    COUNTRY_PACKAGE_VERSIONS = {country: "0.0.0" for country in COUNTRIES}

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
    "economy_impact": 1,
    "report_output": 1,
}


def _build_runtime_cache_version(
    scope: str, country_id: str, caller_version: str | None = None
) -> str:
    """
    Build a compact version token for cache keys stored in legacy VARCHAR(10)
    columns. The token changes whenever the relevant runtime or payload schema
    changes, even if the country package version is unchanged.
    """
    schema_version = str(RUNTIME_CACHE_SCHEMA_VERSIONS[scope])
    prefix = "e" if scope == "economy_impact" else "r"
    digest_length = 10 - len(prefix) - len(schema_version)
    if digest_length < 4:
        raise ValueError(
            f"Runtime cache version for {scope} does not fit in VARCHAR(10)"
        )

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
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:digest_length]
    return f"{prefix}{schema_version}{digest}"


def get_economy_impact_cache_version(
    country_id: str, caller_version: str | None = None
) -> str:
    return _build_runtime_cache_version("economy_impact", country_id, caller_version)


def get_report_output_cache_version(country_id: str) -> str:
    return _build_runtime_cache_version("report_output", country_id)


# Valid region types for each country
# These define the geographic scope categories for regions
US_REGION_TYPES = (
    "national",  # National level (e.g., "us")
    "state",  # US states (e.g., "state/ca", "state/ny")
    "place",  # US Census places (e.g., "place/NJ-57000")
    "congressional_district",  # US congressional districts (e.g., "congressional_district/CA-37")
)

UK_REGION_TYPES = (
    "national",  # National level (e.g., "uk")
    "country",  # UK countries (e.g., "country/england", "country/scotland")
    "constituency",  # UK parliamentary constituencies (e.g., "constituency/Aldershot")
    "local_authority",  # UK local authorities (e.g., "local_authority/Maidstone")
)

# Valid region prefixes for each country
# These define the allowed geographic scope prefixes in region names
REGION_PREFIXES = {
    "us": [
        "state/",  # US states (e.g., "state/ca", "state/ny")
        "place/",  # US Census places (e.g., "place/NJ-57000")
        "congressional_district/",  # US congressional districts (e.g., "congressional_district/CA-37")
    ],
    "uk": [
        "country/",  # UK countries (e.g., "country/england", "country/scotland")
        "constituency/",  # UK parliamentary constituencies (e.g., "constituency/Aldershot")
        "local_authority/",  # UK local authorities (e.g., "local_authority/Maidstone")
    ],
}

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
