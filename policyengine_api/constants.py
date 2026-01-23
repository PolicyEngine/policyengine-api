from pathlib import Path
import pkg_resources
from datetime import datetime

REPO = Path(__file__).parents[1]
GET = "GET"
POST = "POST"
UPDATE = "UPDATE"
LIST = "LIST"
VERSION = "3.33.4"
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
    COUNTRY_PACKAGE_VERSIONS = {
        country: pkg_resources.get_distribution(package_name).version
        for country, package_name in zip(COUNTRIES, COUNTRY_PACKAGE_NAMES)
    }
except:
    COUNTRY_PACKAGE_VERSIONS = {country: "0.0.0" for country in COUNTRIES}

# Valid region types for each country
# These define the geographic scope categories for regions
US_REGION_TYPES = (
    "national",  # National level (e.g., "us")
    "state",  # US states (e.g., "state/ca", "state/ny")
    "city",  # US cities (e.g., "city/nyc")
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
        "city/",  # US cities (e.g., "city/nyc")
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
