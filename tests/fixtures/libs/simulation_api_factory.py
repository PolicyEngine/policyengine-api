"""
Test fixtures for simulation_api_factory.

This module provides fixtures for testing the simulation API factory
that switches between GCP and Modal backends.
"""

import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def mock_env_use_modal_true():
    """Set USE_MODAL_SIMULATION_API to true."""
    with patch.dict(
        "os.environ",
        {"USE_MODAL_SIMULATION_API": "true"},
    ):
        yield


@pytest.fixture
def mock_env_use_modal_false():
    """Set USE_MODAL_SIMULATION_API to false."""
    with patch.dict(
        "os.environ",
        {"USE_MODAL_SIMULATION_API": "false"},
    ):
        yield


@pytest.fixture
def mock_env_use_modal_unset():
    """Ensure USE_MODAL_SIMULATION_API is not set."""
    with patch.dict(
        "os.environ",
        {},
        clear=True,
    ):
        # Re-patch to only clear the specific key
        import os

        env_copy = dict(os.environ)
        env_copy.pop("USE_MODAL_SIMULATION_API", None)
        with patch.dict("os.environ", env_copy, clear=True):
            yield


@pytest.fixture
def mock_factory_logger():
    """Mock logger for simulation_api_factory."""
    with patch(
        "policyengine_api.libs.simulation_api_factory.logger"
    ) as mock:
        yield mock


@pytest.fixture
def mock_simulation_api_modal_instance():
    """Mock the Modal simulation API instance."""
    mock_instance = MagicMock()
    mock_instance.base_url = "https://mock-modal-api.modal.run"
    with patch(
        "policyengine_api.libs.simulation_api_factory.simulation_api_modal",
        mock_instance,
    ):
        yield mock_instance


@pytest.fixture
def mock_simulation_api_gcp_class():
    """Mock the GCP SimulationAPI class."""
    mock_instance = MagicMock()
    mock_instance.project = "mock-project"
    mock_instance.location = "us-central1"
    mock_instance.workflow = "simulation-workflow"
    with patch(
        "policyengine_api.libs.simulation_api_factory.SimulationAPI",
        return_value=mock_instance,
    ) as mock_class:
        yield mock_class, mock_instance
