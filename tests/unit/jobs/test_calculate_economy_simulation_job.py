import pytest
import unittest.mock as mock
import numpy as np
import pandas as pd

from policyengine_api.jobs.calculate_economy_simulation_job import (
    CalculateEconomySimulationJob,
)
from tests.unit.fixtures.jobs.test_calculate_economy_simulation_job import (
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
