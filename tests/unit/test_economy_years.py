"""Each country's society-wide years, defined once in policyengine_api.economy_years."""

from itertools import pairwise

import pytest

from policyengine_api import spm
from policyengine_api.data.v2.catalog import extraction
from policyengine_api.economy_years import (
    ECONOMY_YEARS,
    UK_ECONOMY_YEARS,
    US_ECONOMY_YEARS,
    US_FIRST_ECONOMY_YEAR,
    US_LAST_ECONOMY_YEAR,
    dataset_year_unavailable_message,
)
from tests.fixtures.v2_catalog import normalized_catalog


def test_us_years_start_in_2024():
    assert US_FIRST_ECONOMY_YEAR == 2024


def test_us_years_are_every_year_from_the_last_to_the_first_newest_first():
    assert US_ECONOMY_YEARS[0] == US_LAST_ECONOMY_YEAR
    assert US_ECONOMY_YEARS[-1] == US_FIRST_ECONOMY_YEAR
    assert all(newer - older == 1 for newer, older in pairwise(US_ECONOMY_YEARS))


def test_the_last_us_year_is_the_last_year_of_the_bundles_spm_forecast():
    """Fail when the bundle's SPM forecast ends in another year.

    Years after the forecast would fail with SPM_YEAR_UNAVAILABLE, and forecast
    years after US_LAST_ECONOMY_YEAR would not be offered.
    """
    configured = spm._certified_spm_configuration("us", selection_sent=False)
    _, forecast = spm._certified_bundle_spm(configured)

    assert max(forecast.years) == US_LAST_ECONOMY_YEAR


def test_uk_years_are_2024_to_2032_oldest_first():
    assert UK_ECONOMY_YEARS == (
        2024,
        2025,
        2026,
        2027,
        2028,
        2029,
        2030,
        2031,
        2032,
    )


def test_catalog_extraction_uses_the_same_years():
    assert extraction.METADATA_TIME_PERIODS is ECONOMY_YEARS


@pytest.mark.parametrize("country_id", ["us", "uk"])
def test_each_extracted_catalog_version_stores_its_countrys_years(country_id):
    model_version = normalized_catalog().country(country_id).model_version

    assert model_version.metadata_time_periods == ECONOMY_YEARS[country_id]


@pytest.mark.parametrize(
    ("country_id", "year", "message"),
    [
        (
            "us",
            "2022",
            f"US results are available for {US_FIRST_ECONOMY_YEAR} to "
            f"{US_LAST_ECONOMY_YEAR}. 2022 is outside the years the current US "
            "model and data cover.",
        ),
        (
            "uk",
            "2033",
            "UK results are available for 2024 to 2032. 2033 is outside the "
            "years the current UK model and data cover.",
        ),
    ],
)
def test_the_unavailable_year_message_names_the_years_and_the_request(
    country_id, year, message
):
    assert dataset_year_unavailable_message(country_id, year) == message
