import pytest
from policyengine_api.services.metadata_service import MetadataService
from policyengine_api.country import COUNTRIES

class TestMetadataService:
    @pytest.fixture
    def service(self):
        return MetadataService()

    def test_get_metadata_success(self, service, test_db):
        # GIVEN a valid country ID
        country_id = "uk"

        # WHEN we call get_metadata
        result = service.get_metadata(country_id)

        # THEN it should return the country's metadata
        assert result is not None
        assert isinstance(result, dict)
        # Verify all required metadata fields are present
        assert "variables" in result
        assert "parameters" in result
        assert "entities" in result
        assert "variableModules" in result
        assert "economy_options" in result
        assert "current_law_id" in result
        assert "basicInputs" in result
        assert "modelled_policies" in result
        assert "version" in result

        # Verify some UK-specific data
        assert result["current_law_id"] == 1
        uk_regions = result["economy_options"]["region"]
        assert any(region["name"] == "uk" for region in uk_regions)
        assert any(region["name"] == "eng" for region in uk_regions)
        assert any(region["name"] == "scot" for region in uk_regions)

    def test_get_metadata_nonexistent_country(self, service, test_db):
        # GIVEN a non-existent country ID
        invalid_country_id = "invalid_country"

        # WHEN we call get_metadata with an invalid country
        # THEN it should raise a RuntimeError with appropriate message
        with pytest.raises(RuntimeError) as exc_info:
            service.get_metadata(invalid_country_id)
        
        assert str(exc_info.value) == f"Attempted to get metadata for a nonexistant country: '{invalid_country_id}'"

    def test_get_metadata_empty_country_id(self, service, test_db):
        # GIVEN an empty country ID
        empty_country_id = ""

        # WHEN we call get_metadata with an empty country ID
        # THEN it should raise a RuntimeError
        with pytest.raises(RuntimeError) as exc_info:
            service.get_metadata(empty_country_id)

        assert str(exc_info.value) == f"Attempted to get metadata for a nonexistant country: '{empty_country_id}'"

    def test_get_metadata_all_supported_countries(self, service, test_db):
        # GIVEN all supported country IDs
        supported_countries = ["uk", "us", "ca", "ng", "il"]

        # WHEN we try to get metadata for each supported country
        for country_id in supported_countries:
            metadata = service.get_metadata(country_id)
            
            # THEN it should return valid metadata for each country
            assert metadata is not None
            assert isinstance(metadata, dict)
            
            # Verify basic structure
            assert "variables" in metadata
            assert "parameters" in metadata
            assert "entities" in metadata
            assert "current_law_id" in metadata
            
            # Verify country-specific data
            country_id_mapping = {
                "uk": 1,
                "us": 2,
                "ca": 3,
                "ng": 4,
                "il": 5
            }
            assert metadata["current_law_id"] == country_id_mapping[country_id]
            
            # Verify region data exists
            assert "economy_options" in metadata
            assert "region" in metadata["economy_options"]
            regions = metadata["economy_options"]["region"]
            assert any(region["name"] == country_id for region in regions)
            
            # Verify time periods exist
            assert "time_period" in metadata["economy_options"]
            assert len(metadata["economy_options"]["time_period"]) > 0

    def test_get_metadata_verify_uk_specific_data(self, service, test_db):
        # GIVEN the UK country ID
        country_id = "uk"

        # WHEN we get the metadata
        metadata = service.get_metadata(country_id)

        # THEN it should have UK-specific data
        uk_regions = metadata["economy_options"]["region"]
        expected_regions = ["uk", "eng", "scot", "wales", "ni"]
        for region in expected_regions:
            assert any(r["name"] == region for r in uk_regions)

        # Verify UK time periods
        time_periods = metadata["economy_options"]["time_period"]
        assert any(period["name"] == 2024 for period in time_periods)
        assert any(period["name"] == 2025 for period in time_periods)

    def test_get_metadata_verify_us_specific_data(self, service, test_db):
        # GIVEN the US country ID
        country_id = "us"

        # WHEN we get the metadata
        metadata = service.get_metadata(country_id)

        # THEN it should have US-specific data
        us_regions = metadata["economy_options"]["region"]
        expected_regions = ["us", "ca", "ny", "tx", "fl"]  # Sample of states
        for region in expected_regions:
            assert any(r["name"] == region for r in us_regions)

        # Verify US datasets
        datasets = metadata["economy_options"]["datasets"]
        assert any(dataset["name"] == "cps" for dataset in datasets)
        assert any(dataset["name"] == "enhanced_cps" for dataset in datasets)

        # Verify US time periods
        time_periods = metadata["economy_options"]["time_period"]
        assert any(period["name"] == 2023 for period in time_periods)
        assert any(period["name"] == 2024 for period in time_periods)