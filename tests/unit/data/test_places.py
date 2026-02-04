import pytest

from policyengine_api.data.places import (
    parse_place_code,
    validate_place_code,
)


class TestParsePlaceCode:
    """Tests for the parse_place_code function."""

    def test__given_valid_place_code__returns_tuple(self):
        state, fips = parse_place_code("NJ-57000")
        assert state == "NJ"
        assert fips == "57000"

    def test__given_lowercase_place_code__returns_tuple(self):
        state, fips = parse_place_code("ca-44000")
        assert state == "ca"
        assert fips == "44000"

    def test__given_no_hyphen__raises_value_error(self):
        with pytest.raises(ValueError) as exc_info:
            parse_place_code("NJ57000")
        assert "Invalid place format" in str(exc_info.value)

    def test__given_empty_string__raises_value_error(self):
        with pytest.raises(ValueError) as exc_info:
            parse_place_code("")
        assert "Invalid place format" in str(exc_info.value)


class TestValidatePlaceCode:
    """Tests for the validate_place_code function."""

    def test__given_valid_place_code__no_error(self):
        # Should not raise
        validate_place_code("NJ-57000")
        validate_place_code("ca-44000")
        validate_place_code("TX-35000")

    def test__given_invalid_state__raises_value_error(self):
        with pytest.raises(ValueError) as exc_info:
            validate_place_code("XX-57000")
        assert "Invalid state in place code" in str(exc_info.value)

    def test__given_non_digit_fips__raises_value_error(self):
        with pytest.raises(ValueError) as exc_info:
            validate_place_code("NJ-abcde")
        assert "Invalid FIPS code" in str(exc_info.value)

    def test__given_short_fips__raises_value_error(self):
        with pytest.raises(ValueError) as exc_info:
            validate_place_code("NJ-5700")
        assert "Invalid FIPS code" in str(exc_info.value)

    def test__given_long_fips__raises_value_error(self):
        with pytest.raises(ValueError) as exc_info:
            validate_place_code("NJ-570001")
        assert "Invalid FIPS code" in str(exc_info.value)

    def test__given_no_hyphen__raises_value_error(self):
        with pytest.raises(ValueError) as exc_info:
            validate_place_code("NJ57000")
        assert "Invalid place format" in str(exc_info.value)
