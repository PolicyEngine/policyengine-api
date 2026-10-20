"""The Public API serves only the US and the UK.

Canada, Nigeria and Israel are no longer served: their country packages are
not installed, their requests are rejected as unknown countries, and their
country-specific metadata branches are gone.
"""

import tomllib
from pathlib import Path

import pytest

from policyengine_api.constants import COUNTRIES, COUNTRY_PACKAGE_NAMES
from policyengine_api.country_validation import (
    InvalidCountryError,
    ensure_supported_country,
)
from policyengine_api.utils.get_current_law import get_current_law_policy_id

REPO = Path(__file__).resolve().parents[2]
REMOVED_COUNTRY_IDS = ("ca", "ng", "il")
REMOVED_COUNTRY_PACKAGES = ("policyengine-canada", "policyengine-ng", "policyengine-il")


def _normalized(package_name: str) -> str:
    return package_name.replace("_", "-").lower()


def test_only_the_us_and_the_uk_are_served():
    assert COUNTRIES == ("uk", "us")
    assert COUNTRY_PACKAGE_NAMES == ("policyengine_uk", "policyengine_us")


def test_removed_country_packages_are_not_dependencies():
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    dependency_names = {
        _normalized(dependency.split("==")[0].split(">=")[0].split("[")[0])
        for dependency in project["project"]["dependencies"]
    }
    locked_names = {
        _normalized(package["name"])
        for package in tomllib.loads((REPO / "uv.lock").read_text(encoding="utf-8"))[
            "package"
        ]
    }

    for package_name in REMOVED_COUNTRY_PACKAGES:
        assert package_name not in dependency_names
        assert package_name not in locked_names


@pytest.mark.parametrize("country_id", REMOVED_COUNTRY_IDS)
def test_removed_countries_are_rejected_as_unknown(country_id):
    with pytest.raises(InvalidCountryError) as error:
        ensure_supported_country(country_id)

    assert str(error.value) == (
        f"Country {country_id} not found. Available countries are: uk, us"
    )


@pytest.mark.parametrize("country_id", REMOVED_COUNTRY_IDS)
def test_removed_countries_have_no_current_law_policy(country_id):
    with pytest.raises(KeyError):
        get_current_law_policy_id(country_id)


def test_country_metadata_has_no_removed_country_branches():
    source = (REPO / "policyengine_api/country.py").read_text(encoding="utf-8")

    for label in ("Canada", "Nigeria", "Israel"):
        assert label not in source
    for package_name in ("policyengine_canada", "policyengine_ng", "policyengine_il"):
        assert package_name not in source
