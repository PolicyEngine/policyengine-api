from pathlib import Path
from importlib.metadata import PackageNotFoundError, distributions, version
from datetime import datetime
import hashlib

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
try:
    _dist_versions = {d.metadata["Name"]: d.version for d in distributions()}
    COUNTRY_PACKAGE_VERSIONS = {
        country: _dist_versions.get(package_name.replace("_", "-"), "0.0.0")
        for country, package_name in zip(COUNTRIES, COUNTRY_PACKAGE_NAMES)
    }
except Exception:
    COUNTRY_PACKAGE_VERSIONS = {country: "0.0.0" for country in COUNTRIES}

try:
    POLICYENGINE_CORE_VERSION = version("policyengine")
except PackageNotFoundError:
    POLICYENGINE_CORE_VERSION = "0.0.0"

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
