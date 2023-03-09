from pathlib import Path
import pkg_resources

REPO = Path(__file__).parents[1]
GET = "GET"
POST = "POST"
UPDATE = "UPDATE"
LIST = "LIST"
VERSION = "0.10.3"
COUNTRIES = ("uk", "us", "ca", "ng")
COUNTRY_PACKAGE_NAMES = (
    "policyengine_uk",
    "policyengine_us",
    "policyengine_canada",
    "policyengine_ng",
)
COUNTRY_PACKAGE_VERSIONS = {
    country: pkg_resources.get_distribution(package_name).version
    for country, package_name in zip(COUNTRIES, COUNTRY_PACKAGE_NAMES)
}

__version__ = VERSION
