from pathlib import Path
import pkg_resources
from datetime import datetime

REPO = Path(__file__).parents[1]
GET = "GET"
POST = "POST"
UPDATE = "UPDATE"
LIST = "LIST"
VERSION = "3.29.2"
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

# Valid region prefixes for each country
# These define the allowed geographic scope prefixes in region names
REGION_PREFIXES = {
    "us": [
        "state/",  # US states (e.g., "state/ca", "state/ny")
        "congressional_district/",  # US congressional districts (e.g., "congressional_district/CA-37")
    ],
    "uk": [
        "country/",  # UK countries (e.g., "country/england", "country/scotland")
        "constituency/",  # UK parliamentary constituencies (e.g., "constituency/Aldershot")
    ],
}

__version__ = VERSION
