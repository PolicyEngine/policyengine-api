"""Each country's society-wide years, defined once in policyengine_api.economy_years."""

import pytest

from policyengine_api.data.v2.catalog import extraction
from policyengine_api.economy_years import (
    ECONOMY_YEARS,
    UK_ECONOMY_YEARS,
    US_ECONOMY_YEARS,
    dataset_year_unavailable_message,
)
from tests.fixtures.v2_catalog import normalized_catalog


def test_us_years_are_2024_to_2035_newest_first():
    assert US_ECONOMY_YEARS == (
        2035,
        2034,
        2033,
        2032,
        2031,
        2030,
        2029,
        2028,
        2027,
        2026,
        2025,
        2024,
    )


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
            "US results are available for 2024 to 2035. 2022 is outside the "
            "years the current US model and data cover.",
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
