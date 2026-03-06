import pytest
import pandas as pd
from pathlib import Path

from policyengine_api.country import COUNTRIES


class TestUKCountryMetadata:
    """Tests for UK country metadata, specifically local authority loading."""

    @pytest.fixture
    def uk_country(self):
        return COUNTRIES["uk"]

    @pytest.fixture
    def uk_regions(self, uk_country):
        return uk_country.metadata["economy_options"]["region"]

    def test__uk_metadata_contains_local_authorities(self, uk_regions):
        """Verify that local authorities are included in UK region options."""
        local_authority_regions = [
            r for r in uk_regions if r.get("type") == "local_authority"
        ]
        assert len(local_authority_regions) > 0

    def test__uk_has_360_local_authorities(self, uk_regions):
        """Verify the correct number of local authorities are loaded."""
        local_authority_regions = [
            r for r in uk_regions if r.get("type") == "local_authority"
        ]
        assert len(local_authority_regions) == 360

    def test__local_authority_regions_have_correct_name_format(self, uk_regions):
        """Verify local authority region names have the correct prefix."""
        local_authority_regions = [
            r for r in uk_regions if r.get("type") == "local_authority"
        ]
        for region in local_authority_regions:
            assert region["name"].startswith("local_authority/")

    def test__local_authority_regions_have_labels(self, uk_regions):
        """Verify all local authority regions have labels."""
        local_authority_regions = [
            r for r in uk_regions if r.get("type") == "local_authority"
        ]
        for region in local_authority_regions:
            assert "label" in region
            assert len(region["label"]) > 0

    def test__local_authority_regions_have_type_field(self, uk_regions):
        """Verify all local authority regions have type field set correctly."""
        local_authority_regions = [
            r for r in uk_regions if r.get("type") == "local_authority"
        ]
        for region in local_authority_regions:
            assert region["type"] == "local_authority"

    def test__specific_local_authorities_present(self, uk_regions):
        """Verify specific local authorities are present in metadata."""
        local_authority_names = [
            r["name"] for r in uk_regions if r.get("type") == "local_authority"
        ]
        # Check some well-known local authorities
        assert "local_authority/Hartlepool" in local_authority_names
        assert "local_authority/Middlesbrough" in local_authority_names
        assert "local_authority/Leicester" in local_authority_names

    def test__uk_still_has_constituencies(self, uk_regions):
        """Verify constituencies are still present after adding local authorities."""
        constituency_regions = [
            r for r in uk_regions if r.get("type") == "constituency"
        ]
        assert len(constituency_regions) == 650

    def test__uk_has_all_region_types(self, uk_regions):
        """Verify all expected region types are present."""
        types = set(r.get("type") for r in uk_regions)
        assert "national" in types
        assert "country" in types
        assert "constituency" in types
        assert "local_authority" in types


class TestLocalAuthoritiesDataFile:
    """Tests for the local authorities CSV data file."""

    @pytest.fixture
    def local_authorities_df(self):
        path = (
            Path(__file__).parents[2]
            / "policyengine_api"
            / "data"
            / "local_authorities_2021.csv"
        )
        return pd.read_csv(path)

    def test__file_has_correct_columns(self, local_authorities_df):
        """Verify the CSV has the expected columns."""
        expected_columns = {"code", "name", "x", "y"}
        assert expected_columns == set(local_authorities_df.columns)

    def test__file_has_360_local_authorities(self, local_authorities_df):
        """Verify the correct number of local authorities in file."""
        assert len(local_authorities_df) == 360

    def test__all_codes_are_valid_ons_codes(self, local_authorities_df):
        """Verify all codes follow ONS local authority code patterns."""
        for code in local_authorities_df["code"]:
            # ONS codes start with E (England), S (Scotland), W (Wales), or N (Northern Ireland)
            assert code[0] in ["E", "S", "W", "N"]

    def test__all_names_are_non_empty(self, local_authorities_df):
        """Verify all local authority names are non-empty."""
        for name in local_authorities_df["name"]:
            assert len(str(name)) > 0

    def test__coordinates_are_numeric(self, local_authorities_df):
        """Verify x and y coordinates are numeric."""
        assert local_authorities_df["x"].dtype in ["float64", "int64"]
        assert local_authorities_df["y"].dtype in ["float64", "int64"]

    def test__english_local_authorities_have_e_prefix(self, local_authorities_df):
        """Verify English local authorities have E prefix codes."""
        english_las = local_authorities_df[
            local_authorities_df["code"].str.startswith("E")
        ]
        # England has 296 local authorities (majority of the 360 total)
        assert len(english_las) == 296

    def test__scottish_local_authorities_have_s_prefix(self, local_authorities_df):
        """Verify Scottish local authorities have S prefix codes."""
        scottish_las = local_authorities_df[
            local_authorities_df["code"].str.startswith("S")
        ]
        # Scotland has 32 council areas
        assert len(scottish_las) == 32

    def test__welsh_local_authorities_have_w_prefix(self, local_authorities_df):
        """Verify Welsh local authorities have W prefix codes."""
        welsh_las = local_authorities_df[
            local_authorities_df["code"].str.startswith("W")
        ]
        # Wales has 22 principal areas
        assert len(welsh_las) == 22
