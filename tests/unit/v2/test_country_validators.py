"""The comparison of stored countries rows with the country list in code."""

from __future__ import annotations

import pytest

from policyengine_api.services.v2.countries.validators import (
    CountryListMismatchError,
    validate_countries_match_code_list,
)


def test_the_same_countries_in_any_order_match() -> None:
    validate_countries_match_code_list(
        stored_country_ids=["us", "uk"],
        listed_country_ids=("uk", "us"),
    )


def test_a_listed_country_without_a_row_is_a_mismatch() -> None:
    with pytest.raises(CountryListMismatchError) as raised:
        validate_countries_match_code_list(
            stored_country_ids=["uk"],
            listed_country_ids=("uk", "us"),
        )

    assert raised.value.listed_without_row == ("us",)
    assert raised.value.rows_not_listed == ()
    assert str(raised.value) == (
        "the countries table does not match the country list in code: "
        "listed without a row: us; rows not listed: none"
    )


def test_a_row_for_an_unlisted_country_is_a_mismatch() -> None:
    with pytest.raises(CountryListMismatchError) as raised:
        validate_countries_match_code_list(
            stored_country_ids=["ca", "uk", "us"],
            listed_country_ids=("uk", "us"),
        )

    assert raised.value.listed_without_row == ()
    assert raised.value.rows_not_listed == ("ca",)


def test_every_difference_is_reported_in_order() -> None:
    with pytest.raises(CountryListMismatchError) as raised:
        validate_countries_match_code_list(
            stored_country_ids=["ng", "ca"],
            listed_country_ids=("us", "uk"),
        )

    assert raised.value.listed_without_row == ("uk", "us")
    assert raised.value.rows_not_listed == ("ca", "ng")
    assert str(raised.value) == (
        "the countries table does not match the country list in code: "
        "listed without a row: uk, us; rows not listed: ca, ng"
    )


def test_an_empty_table_misses_every_listed_country() -> None:
    with pytest.raises(CountryListMismatchError) as raised:
        validate_countries_match_code_list(
            stored_country_ids=[],
            listed_country_ids=("uk", "us"),
        )

    assert raised.value.listed_without_row == ("uk", "us")
