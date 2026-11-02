"""The Public API's one country list, and the lists that derive from it."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from policyengine_api.constants import REPO
from policyengine_api.data.v2.catalog import extraction
from policyengine_api.query_parameters import CountryId
from policyengine_api.supported_countries import (
    SUPPORTED_COUNTRY_IDS,
    SupportedCountryId,
)

# Runs in a fresh interpreter: it adds a country to the one list before any
# module that derives from it is imported, then reports what each derived
# list contains. PolicyEngine.py is replaced by a stand-in, because importing
# the real package builds every country model.
EXTENDED_LIST_SCRIPT = """
import json
import sys
from types import ModuleType, SimpleNamespace
from typing import Literal, get_args

import policyengine_api.supported_countries as supported_countries

supported_countries.SupportedCountryId = Literal["us", "uk", "zz"]
supported_countries.SUPPORTED_COUNTRY_IDS = get_args(
    supported_countries.SupportedCountryId
)

installed_policyengine = ModuleType("policyengine")
for country_id in ("us", "uk", "zz", "ca"):
    setattr(
        installed_policyengine,
        country_id,
        SimpleNamespace(model=f"{country_id} model"),
    )
installed_bundle = ModuleType("policyengine.bundle")
installed_bundle.get_current_bundle = dict
sys.modules["policyengine"] = installed_policyengine
sys.modules["policyengine.bundle"] = installed_bundle

from pydantic import TypeAdapter

from policyengine_api.data.v2.catalog import catalog_selection, extraction
from policyengine_api.query_parameters import CountryId
from scripts import process_v1_household_mirror_event

captured_arguments = {}


def capture_extraction(**arguments):
    captured_arguments.update(arguments)


extraction.extract_catalog = capture_extraction
extraction.extract_installed_catalog()
country_option = next(
    action
    for action in process_v1_household_mirror_event._parser()._actions
    if action.dest == "country_id"
)
print(
    json.dumps(
        {
            "country_type": TypeAdapter(CountryId).validate_python("ZZ"),
            "extracted_countries": list(extraction.SUPPORTED_COUNTRIES),
            "required_dependencies": list(extraction.REQUIRED_DEPENDENCIES),
            "installed_models": captured_arguments["models"],
            "dual_write_countries": sorted(catalog_selection.SUPPORTED_V2_COUNTRY_IDS),
            "household_copy_countries": list(country_option.choices),
        }
    )
)
"""


def test_the_country_list_is_the_us_and_the_uk_in_catalog_order() -> None:
    assert SUPPORTED_COUNTRY_IDS == ("us", "uk")
    assert get_args(SupportedCountryId) == SUPPORTED_COUNTRY_IDS


def test_the_v2_country_type_accepts_exactly_the_listed_countries() -> None:
    country_id_adapter = TypeAdapter(CountryId)

    for country_id in SUPPORTED_COUNTRY_IDS:
        assert country_id_adapter.validate_python(country_id) == country_id
        assert country_id_adapter.validate_python(country_id.upper()) == country_id
    for unlisted_country_id in ("ca", "ng", "il", ""):
        with pytest.raises(ValidationError):
            country_id_adapter.validate_python(unlisted_country_id)


def test_every_country_list_follows_a_country_added_to_the_one_list() -> None:
    result = subprocess.run(
        [sys.executable, "-c", EXTENDED_LIST_SCRIPT],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    derived_lists = json.loads(result.stdout.strip().splitlines()[-1])
    assert derived_lists == {
        "country_type": "zz",
        "extracted_countries": ["us", "uk", "zz"],
        "required_dependencies": [
            "policyengine-core",
            "policyengine-us",
            "policyengine-uk",
            "policyengine-zz",
        ],
        # The installed package's other countries are not extracted.
        "installed_models": {
            "us": "us model",
            "uk": "uk model",
            "zz": "zz model",
        },
        "dual_write_countries": ["uk", "us", "zz"],
        "household_copy_countries": ["us", "uk", "zz"],
    }


def test_catalog_settings_cover_exactly_the_listed_countries() -> None:
    # Each listed country needs reviewed catalog settings, so adding a country
    # without them fails here rather than during publication.
    listed_countries = set(SUPPORTED_COUNTRY_IDS)

    assert set(extraction.REVIEWED_DEFAULT_DATASETS) == listed_countries
    assert set(extraction.CURRENT_LAW_IDS) == listed_countries
    assert set(extraction.METADATA_TIME_PERIODS) == listed_countries
