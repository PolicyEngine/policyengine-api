import pytest
import unittest.mock as mock
import numpy as np
import pandas as pd
import json

from policyengine_api.jobs.calculate_economy_simulation_job import (
    CalculateEconomySimulationJob,
    SimulationAPI,
)
from tests.fixtures.jobs.calculate_economy_simulation_job import (
    mock_huggingface_downloads,
    mock_country,
    mock_h5py_weights,
    mock_constituency_names,
    mock_simulation,
)


class TestUKCountryFilters:
    """Test that UK country filters work correctly with constituency outputs."""

    def _run_country_filter_test(
        self,
        mock_huggingface_downloads,
        mock_country,
        mock_h5py_weights,
        mock_constituency_names,
        mock_simulation,
        region,
    ):
        """Helper method to run a country filter test for a specific region."""
        # Set up the job
        job = CalculateEconomySimulationJob()

        # Mock the CountryMicrosimulation creation
        mock_country.country_package.Microsimulation.return_value = (
            mock_simulation
        )

        # Call the method with the specified region
        with mock.patch(
            "policyengine_api.jobs.calculate_economy_simulation_job.ENHANCED_FRS",
            "mock_dataset",
        ):
            job._create_simulation_uk(mock_country, {}, region, "2025")

        # Check that calculate was called
        mock_simulation.calculate.assert_called_with(
            "household_net_income", 2025
        )

        # Check that set_input was called with the right weights
        calls = mock_simulation.set_input.call_args_list

        # The last set_input call should have the filtered weights
        last_call = calls[-1]
        args, kwargs = last_call

        # args[0] is the variable name, args[1] is the year, args[2] is the weights array
        assert args[0] == "household_weight"
        assert args[1] == 2025

        # The weight array should be 1D with length 100 (number of households)
        assert args[2].ndim == 1
        assert args[2].shape[0] == 100

        # Verify person and benunit weight arrays were deleted
        mock_simulation.get_holder(
            "person_weight"
        ).delete_arrays.assert_called_once()
        mock_simulation.get_holder(
            "benunit_weight"
        ).delete_arrays.assert_called_once()

    def test_uk_country_england_filter(
        self,
        mock_huggingface_downloads,
        mock_country,
        mock_h5py_weights,
        mock_constituency_names,
        mock_simulation,
    ):
        """Test that the UK country/england filter correctly filters constituencies."""
        self._run_country_filter_test(
            mock_huggingface_downloads,
            mock_country,
            mock_h5py_weights,
            mock_constituency_names,
            mock_simulation,
            "country/england",
        )

    def test_uk_country_scotland_filter(
        self,
        mock_huggingface_downloads,
        mock_country,
        mock_h5py_weights,
        mock_constituency_names,
        mock_simulation,
    ):
        """Test that the UK country/scotland filter correctly filters constituencies."""
        self._run_country_filter_test(
            mock_huggingface_downloads,
            mock_country,
            mock_h5py_weights,
            mock_constituency_names,
            mock_simulation,
            "country/scotland",
        )

    def test_uk_country_wales_filter(
        self,
        mock_huggingface_downloads,
        mock_country,
        mock_h5py_weights,
        mock_constituency_names,
        mock_simulation,
    ):
        """Test that the UK country/wales filter correctly filters constituencies."""
        self._run_country_filter_test(
            mock_huggingface_downloads,
            mock_country,
            mock_h5py_weights,
            mock_constituency_names,
            mock_simulation,
            "country/wales",
        )

    def test_uk_country_ni_filter(
        self,
        mock_huggingface_downloads,
        mock_country,
        mock_h5py_weights,
        mock_constituency_names,
        mock_simulation,
    ):
        """Test that the UK country/ni filter correctly filters constituencies."""
        self._run_country_filter_test(
            mock_huggingface_downloads,
            mock_country,
            mock_h5py_weights,
            mock_constituency_names,
            mock_simulation,
            "country/ni",
        )

    def test_uk_without_region_filter(
        self, mock_huggingface_downloads, mock_country, mock_simulation
    ):
        """Test that without a region filter, no filtering occurs."""
        # Set up the job
        job = CalculateEconomySimulationJob()

        # Mock the CountryMicrosimulation creation
        mock_country.country_package.Microsimulation.return_value = (
            mock_simulation
        )

        # Call the method with no region filter
        with mock.patch(
            "policyengine_api.jobs.calculate_economy_simulation_job.ENHANCED_FRS",
            "mock_dataset",
        ):
            job._create_simulation_uk(mock_country, {}, "uk", "2025")

        # Only default simulation creation should happen, no constituency filtering
        assert mock_simulation.calculate.call_count == 0
        assert mock_simulation.get_holder.call_count == 0


class TestSimulationAPI:
    class TestSetupSimOptions:
        test_country_id = "us"
        test_reform_policy = json.dumps(
            {"sample_param": {"2024-01-01.2100-12-31": 15}}
        )
        test_current_law_baseline_policy = json.dumps({})
        test_region = "us"
        test_dataset = None
        test_time_period = "2025"
        test_scope = "macro"

        def test__given_valid_options__returns_correct_sim_options(self):

            # Create an instance of the class
            sim_api = SimulationAPI()

            # Call the method with the test data; patch setup_region and setup_data methods
            sim_options = sim_api._setup_sim_options(
                self.test_country_id,
                self.test_reform_policy,
                self.test_current_law_baseline_policy,
                self.test_region,
                self.test_dataset,
                self.test_time_period,
                self.test_scope,
            )

            # Assert the expected values in the returned dictionary
            assert sim_options["country"] == self.test_country_id
            assert sim_options["scope"] == self.test_scope
            assert sim_options["reform"] == json.loads(self.test_reform_policy)
            assert sim_options["baseline"] == json.loads(
                self.test_current_law_baseline_policy
            )
            assert sim_options["time_period"] == self.test_time_period
            assert sim_options["region"] == "us"
            assert sim_options["data"] == None

        def test__given_us_state__returns_correct_sim_options(self):
            # Test with a US state
            country_id = "us"
            reform_policy = json.dumps(
                {"sample_param": {"2024-01-01.2100-12-31": 15}}
            )
            current_law_baseline_policy = json.dumps({})
            region = "ca"
            dataset = None
            time_period = "2025"
            scope = "macro"

            # Create an instance of the class
            sim_api = SimulationAPI()
            # Call the method
            sim_options = sim_api._setup_sim_options(
                country_id,
                reform_policy,
                current_law_baseline_policy,
                region,
                dataset,
                time_period,
                scope,
            )
            # Assert the expected values in the returned dictionary
            assert sim_options["country"] == country_id
            assert sim_options["scope"] == scope
            assert sim_options["reform"] == json.loads(reform_policy)
            assert sim_options["baseline"] == json.loads(
                current_law_baseline_policy
            )
            assert sim_options["time_period"] == time_period
            assert sim_options["region"] == "state/ca"
            assert (
                sim_options["data"]
                == "gs://policyengine-us-data/pooled_3_year_cps_2023.h5"
            )

        def test__given_enhanced_cps_state__returns_correct_sim_options(self):
            # Test with enhanced_cps dataset
            country_id = "us"
            reform_policy = json.dumps(
                {"sample_param": {"2024-01-01.2100-12-31": 15}}
            )
            current_law_baseline_policy = json.dumps({})
            region = "ut"
            dataset = "enhanced_cps"
            time_period = "2025"
            scope = "macro"

            # Create an instance of the class
            sim_api = SimulationAPI()
            # Call the method
            sim_options = sim_api._setup_sim_options(
                country_id,
                reform_policy,
                current_law_baseline_policy,
                region,
                dataset,
                time_period,
                scope,
            )
            # Assert the expected values in the returned dictionary
            assert sim_options["country"] == country_id
            assert sim_options["scope"] == scope
            assert sim_options["reform"] == json.loads(reform_policy)
            assert sim_options["baseline"] == json.loads(
                current_law_baseline_policy
            )
            assert sim_options["time_period"] == time_period
            assert sim_options["region"] == "state/ut"
            assert (
                sim_options["data"]
                == "gs://policyengine-us-data/enhanced_cps_2024.h5"
            )

    class TestSetupRegion:
        def test__given_us_state__returns_correct_region(self):
            # Test with a US state
            country_id = "us"
            # US states always lowercase two-letter codes
            region = "ca"

            # Create an instance of the class
            sim_api = SimulationAPI()

            # Call the method
            result = sim_api._setup_region(country_id, region)
            # Assert the expected value
            assert result == "state/ca"

        def test__given_non_us_state__returns_correct_region(self):
            # Test with non-US region
            country_id = "uk"
            region = "country/england"

            # Create an instance of the class
            sim_api = SimulationAPI()
            # Call the method
            result = sim_api._setup_region(country_id, region)
            # Assert the expected value
            assert result == region

    class TestSetupData:
        def test__given_enhanced_cps_dataset__returns_correct_gcp_path(self):
            # Test with enhanced_cps dataset
            dataset = "enhanced_cps"
            country_id = "us"
            region = "us"

            # Create an instance of the class
            sim_api = SimulationAPI()
            # Call the method
            result = sim_api._setup_data(dataset, country_id, region)
            # Assert the expected value
            assert result == "gs://policyengine-us-data/enhanced_cps_2024.h5"

        def test__given_us_state_dataset__returns_correct_gcp_path(self):
            # Test with US state dataset
            dataset = "us_state"
            country_id = "us"
            region = "ca"

            # Create an instance of the class
            sim_api = SimulationAPI()
            # Call the method
            result = sim_api._setup_data(dataset, country_id, region)
            # Assert the expected value
            assert (
                result == "gs://policyengine-us-data/pooled_3_year_cps_2023.h5"
            )

        def test__given_us_nationwide_dataset__returns_none(self):
            # Test with US nationwide dataset
            dataset = "us_nationwide"
            country_id = "us"
            region = "us"

            # Create an instance of the class
            sim_api = SimulationAPI()
            # Call the method
            result = sim_api._setup_data(dataset, country_id, region)
            # Assert the expected value
            assert result is None

        def test__given_uk_dataset__returns_none(self):
            # Test with UK dataset
            dataset = "uk_dataset"
            country_id = "uk"
            region = "country/england"

            # Create an instance of the class
            sim_api = SimulationAPI()
            # Call the method
            result = sim_api._setup_data(dataset, country_id, region)
            # Assert the expected value
            assert result is None


class TestSetJobId:
    def test__sets_job_id(self):

        job = object.__new__(CalculateEconomySimulationJob)
        job_id = job._set_job_id()

        assert isinstance(job_id, str)
