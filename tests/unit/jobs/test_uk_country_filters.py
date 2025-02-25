import pytest
import unittest.mock as mock
import numpy as np
import pandas as pd
import h5py

from policyengine_api.jobs.calculate_economy_simulation_job import (
    CalculateEconomySimulationJob,
)


class TestUKCountryFilters:
    """Test that UK country filters work correctly with constituency outputs."""

    @pytest.fixture
    def mock_huggingface_downloads(self, monkeypatch):
        """Mock the huggingface dataset downloads."""

        def mock_download(repo, repo_filename):
            # Return mock file paths for constituency data
            if "constituency_weights" in repo_filename:
                return "mock_weights.h5"
            elif "constituencies_2024.csv" in repo_filename:
                return "mock_constituencies.csv"
            return repo_filename

        monkeypatch.setattr(
            "policyengine_api.jobs.calculate_economy_simulation_job.download_huggingface_dataset",
            mock_download,
        )

    @pytest.fixture
    def mock_country(self):
        """Create a mock UK country object."""
        mock_country = mock.MagicMock()
        mock_country.name = "uk"
        return mock_country

    @pytest.fixture
    def mock_h5py_weights(self, monkeypatch):
        """Mock reading h5py weights."""
        # Create a weight matrix with 650 constituencies and 100 households
        mock_weights = np.ones((650, 100))

        # Create a mock dataset that works with [...] syntax
        mock_dataset = mock.MagicMock()
        mock_dataset.__getitem__.return_value = mock_weights

        # Create a mock group with the dataset
        mock_group = mock.MagicMock()
        mock_group.__getitem__.return_value = mock_dataset

        # Create a mock file
        mock_file = mock.MagicMock()
        mock_file.__enter__.return_value = mock_group
        mock_file.__exit__.return_value = None

        monkeypatch.setattr(h5py, "File", lambda path, mode: mock_file)
        return mock_weights

    @pytest.fixture
    def mock_constituency_names(self, monkeypatch):
        """Mock constituency names dataframe."""
        # Create mock constituency data with English (E), Scottish (S), Welsh (W) and Northern Irish (N) constituencies
        # Need 650 constituencies to match the weights array shape
        codes = []
        names = []

        # Create 400 English constituencies
        for i in range(400):
            codes.append(f"E{i:07d}")
            names.append(f"English Constituency {i}")

        # Create 150 Scottish constituencies
        for i in range(150):
            codes.append(f"S{i:07d}")
            names.append(f"Scottish Constituency {i}")

        # Create 50 Welsh constituencies
        for i in range(50):
            codes.append(f"W{i:07d}")
            names.append(f"Welsh Constituency {i}")

        # Create 50 Northern Irish constituencies
        for i in range(50):
            codes.append(f"N{i:07d}")
            names.append(f"Northern Irish Constituency {i}")

        data = {"code": codes, "name": names}
        mock_df = pd.DataFrame(data)

        monkeypatch.setattr(pd, "read_csv", lambda path: mock_df)
        return mock_df

    @pytest.fixture
    def mock_simulation(self):
        """Create a mock simulation object."""
        simulation = mock.MagicMock()
        simulation.calculate.return_value = None
        simulation.set_input.return_value = None

        # Mock the holder objects
        person_holder = mock.MagicMock()
        benunit_holder = mock.MagicMock()
        simulation.get_holder.side_effect = lambda name: {
            "person_weight": person_holder,
            "benunit_weight": benunit_holder,
        }.get(name)

        return simulation

    def test_uk_country_england_filter(
        self,
        mock_huggingface_downloads,
        mock_country,
        mock_h5py_weights,
        mock_constituency_names,
        mock_simulation,
    ):
        """Test that the UK country/england filter correctly filters constituencies."""
        # Set up the job
        job = CalculateEconomySimulationJob()

        # Mock the CountryMicrosimulation creation
        mock_country.country_package.Microsimulation.return_value = (
            mock_simulation
        )

        # Call the method with country/england region
        with mock.patch(
            "policyengine_api.jobs.calculate_economy_simulation_job.ENHANCED_FRS",
            "mock_dataset",
        ):
            job._create_simulation_uk(
                mock_country, {}, "country/england", "2025"
            )

        # Check that calculate was called
        mock_simulation.calculate.assert_called_with(
            "household_net_income", 2025
        )

        # Check that set_input was called with the right weights
        # We should verify that only English constituencies were included
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

    def test_uk_country_scotland_filter(
        self,
        mock_huggingface_downloads,
        mock_country,
        mock_h5py_weights,
        mock_constituency_names,
        mock_simulation,
    ):
        """Test that the UK country/scotland filter correctly filters constituencies."""
        # Set up the job
        job = CalculateEconomySimulationJob()

        # Mock the CountryMicrosimulation creation
        mock_country.country_package.Microsimulation.return_value = (
            mock_simulation
        )

        # Call the method with country/scotland region
        with mock.patch(
            "policyengine_api.jobs.calculate_economy_simulation_job.ENHANCED_FRS",
            "mock_dataset",
        ):
            job._create_simulation_uk(
                mock_country, {}, "country/scotland", "2025"
            )

        # Check that calculate was called
        mock_simulation.calculate.assert_called_with(
            "household_net_income", 2025
        )

        # The last set_input call should have the filtered weights
        calls = mock_simulation.set_input.call_args_list
        last_call = calls[-1]
        args, kwargs = last_call

        # Check that set_input was called with household_weight
        var_name, year, weights_array = args
        assert var_name == "household_weight"
        assert year == 2025

        # The weight array should be 1D with length 100 (number of households)
        assert weights_array.ndim == 1
        assert weights_array.shape[0] == 100

    def test_uk_country_wales_filter(
        self,
        mock_huggingface_downloads,
        mock_country,
        mock_h5py_weights,
        mock_constituency_names,
        mock_simulation,
    ):
        """Test that the UK country/wales filter correctly filters constituencies."""
        # Set up the job
        job = CalculateEconomySimulationJob()

        # Mock the CountryMicrosimulation creation
        mock_country.country_package.Microsimulation.return_value = (
            mock_simulation
        )

        # Call the method with country/wales region
        with mock.patch(
            "policyengine_api.jobs.calculate_economy_simulation_job.ENHANCED_FRS",
            "mock_dataset",
        ):
            job._create_simulation_uk(
                mock_country, {}, "country/wales", "2025"
            )

        # Check that calculate was called
        mock_simulation.calculate.assert_called_with(
            "household_net_income", 2025
        )

        # Verify person and benunit weight arrays were deleted
        mock_simulation.get_holder(
            "person_weight"
        ).delete_arrays.assert_called_once()
        mock_simulation.get_holder(
            "benunit_weight"
        ).delete_arrays.assert_called_once()

    def test_uk_country_ni_filter(
        self,
        mock_huggingface_downloads,
        mock_country,
        mock_h5py_weights,
        mock_constituency_names,
        mock_simulation,
    ):
        """Test that the UK country/ni filter correctly filters constituencies."""
        # Set up the job
        job = CalculateEconomySimulationJob()

        # Mock the CountryMicrosimulation creation
        mock_country.country_package.Microsimulation.return_value = (
            mock_simulation
        )

        # Call the method with country/ni region
        with mock.patch(
            "policyengine_api.jobs.calculate_economy_simulation_job.ENHANCED_FRS",
            "mock_dataset",
        ):
            job._create_simulation_uk(mock_country, {}, "country/ni", "2025")

        # Check that calculate was called
        mock_simulation.calculate.assert_called_with(
            "household_net_income", 2025
        )

        # Verify person and benunit weight arrays were deleted
        mock_simulation.get_holder(
            "person_weight"
        ).delete_arrays.assert_called_once()
        mock_simulation.get_holder(
            "benunit_weight"
        ).delete_arrays.assert_called_once()

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
