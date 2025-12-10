import pytest
from policyengine_api.services.metadata_service import MetadataService
from policyengine_api.country import COUNTRIES


class TestMetadataService:

    def test_get_metadata_nonexistent_country(self):
        service = MetadataService()
        # GIVEN a non-existent country ID
        invalid_country_id = "invalid_country"

        # WHEN we call get_metadata with an invalid country
        # THEN it should raise an Exception
        with pytest.raises(
            Exception,
            match=f"Attempted to get metadata for a nonexistant country: '{invalid_country_id}'",
        ):
            service.get_metadata(invalid_country_id)

    def test_get_metadata_empty_country_id(self):
        service = MetadataService()

        # GIVEN an empty country ID
        empty_country_id = ""

        # WHEN we call get_metadata with an empty country ID
        # THEN it should raise an Exception
        with pytest.raises(
            Exception,
            match=f"Attempted to get metadata for a nonexistant country: '{empty_country_id}'",
        ):
            service.get_metadata(empty_country_id)

    @pytest.mark.parametrize(
        "country_id, current_law_id, test_regions",
        [
            (
                "uk",
                1,
                [
                    "uk",
                    "country/england",
                    "country/scotland",
                    "country/wales",
                    "country/ni",
                ],
            ),
            (
                "us",
                2,
                [
                    "us",
                    "state/ca",
                    "state/ny",
                    "state/tx",
                    "state/fl",
                    "city/nyc",
                ],
            ),
            ("ca", 3, ["ca"]),
            ("ng", 4, ["ng"]),
            ("il", 5, ["il"]),
        ],
    )
    def test_verify_metadata_for_given_country(
        self, country_id, current_law_id, test_regions
    ):
        """
        Verifies metadata for a specific country contains expected values.

        Args:
            service: The MetadataService fixture
            country_id: Country identifier string
            current_law_id: Expected current law ID for this country
            test_regions: List of region codes that should be present for this country
        """
        # Get metadata for the country
        service = MetadataService()
        metadata = service.get_metadata(country_id)

        # Verify basic structure
        assert metadata is not None
        assert isinstance(metadata, dict)
        assert "variables" in metadata
        assert "parameters" in metadata
        assert "entities" in metadata
        assert "variableModules" in metadata
        assert "current_law_id" in metadata
        assert "economy_options" in metadata
        assert "basicInputs" in metadata
        assert "modelled_policies" in metadata
        assert "version" in metadata

        # Verify country-specific data
        assert metadata["current_law_id"] == current_law_id

        # Verify region data exists
        assert "region" in metadata["economy_options"]
        regions = metadata["economy_options"]["region"]
        for region in test_regions:
            assert any(
                r["name"] == region for r in regions
            ), f"Expected region '{region}' not found"

        # Verify time periods exist and have correct structure
        assert "time_period" in metadata["economy_options"]
        time_periods = metadata["economy_options"]["time_period"]
        assert isinstance(time_periods, list)
        assert len(time_periods) > 0

        # Check time period structure instead of specific values
        for period in time_periods:
            assert "name" in period
            assert "label" in period
            assert isinstance(period["name"], int)
            assert isinstance(period["label"], str)

        # Verify datasets exist and are of correct type
        assert "datasets" in metadata["economy_options"]
        assert isinstance(metadata["economy_options"]["datasets"], list)

    @pytest.mark.parametrize(
        "country_id, expected_types",
        [
            ("uk", ["national", "country", "constituency"]),
            ("us", ["national", "state", "city", "congressional_district"]),
        ],
    )
    def test_verify_region_types_for_given_country(
        self, country_id, expected_types
    ):
        """
        Verifies that all regions for UK and US have a 'type' field
        with valid values.
        """
        service = MetadataService()
        metadata = service.get_metadata(country_id)

        regions = metadata["economy_options"]["region"]
        for region in regions:
            assert (
                "type" in region
            ), f"Region '{region['name']}' missing 'type' field"
            assert (
                region["type"] in expected_types
            ), f"Region '{region['name']}' has invalid type '{region['type']}'"
