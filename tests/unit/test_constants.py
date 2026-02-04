import pytest

from policyengine_api.constants import (
    UK_REGION_TYPES,
    US_REGION_TYPES,
    REGION_PREFIXES,
)


class TestUKRegionTypes:
    """Tests for UK_REGION_TYPES constant."""

    def test__contains_national(self):
        assert "national" in UK_REGION_TYPES

    def test__contains_country(self):
        assert "country" in UK_REGION_TYPES

    def test__contains_constituency(self):
        assert "constituency" in UK_REGION_TYPES

    def test__contains_local_authority(self):
        assert "local_authority" in UK_REGION_TYPES

    def test__has_exactly_four_types(self):
        assert len(UK_REGION_TYPES) == 4


class TestUSRegionTypes:
    """Tests for US_REGION_TYPES constant."""

    def test__contains_national(self):
        assert "national" in US_REGION_TYPES

    def test__contains_state(self):
        assert "state" in US_REGION_TYPES

    def test__contains_place(self):
        assert "place" in US_REGION_TYPES

    def test__contains_congressional_district(self):
        assert "congressional_district" in US_REGION_TYPES

    def test__has_exactly_four_types(self):
        assert len(US_REGION_TYPES) == 4


class TestRegionPrefixes:
    """Tests for REGION_PREFIXES constant."""

    class TestUKPrefixes:
        """Tests for UK region prefixes."""

        def test__uk_key_exists(self):
            assert "uk" in REGION_PREFIXES

        def test__contains_country_prefix(self):
            assert "country/" in REGION_PREFIXES["uk"]

        def test__contains_constituency_prefix(self):
            assert "constituency/" in REGION_PREFIXES["uk"]

        def test__contains_local_authority_prefix(self):
            assert "local_authority/" in REGION_PREFIXES["uk"]

        def test__has_exactly_three_prefixes(self):
            assert len(REGION_PREFIXES["uk"]) == 3

    class TestUSPrefixes:
        """Tests for US region prefixes."""

        def test__us_key_exists(self):
            assert "us" in REGION_PREFIXES

        def test__contains_state_prefix(self):
            assert "state/" in REGION_PREFIXES["us"]

        def test__contains_place_prefix(self):
            assert "place/" in REGION_PREFIXES["us"]

        def test__contains_congressional_district_prefix(self):
            assert "congressional_district/" in REGION_PREFIXES["us"]

        def test__has_exactly_three_prefixes(self):
            assert len(REGION_PREFIXES["us"]) == 3
