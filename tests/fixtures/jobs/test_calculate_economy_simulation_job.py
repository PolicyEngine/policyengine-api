import pytest
import unittest.mock as mock
import numpy as np
import pandas as pd
import h5py


@pytest.fixture
def mock_huggingface_downloads(monkeypatch):
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
def mock_country():
    """Create a mock UK country object."""
    mock_country = mock.MagicMock()
    mock_country.name = "uk"
    return mock_country


@pytest.fixture
def mock_h5py_weights(monkeypatch):
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
def mock_constituency_names(monkeypatch):
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
def mock_simulation():
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

@pytest.fixture
def mock_setup_region():
    """Mock _setup_region to always return 'valid_region'."""
    return "valid_region"

@pytest.fixture
def mock_setup_dataset():
    """Mock _setup_dataset to always return 'valid dataset'."""
    return "valid_dataset"