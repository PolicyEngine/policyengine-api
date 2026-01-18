"""
Test fixtures for SimulationAPIModal.

This module provides mock data, fixtures, and helper functions for testing
the Modal simulation API client.
"""

import pytest
from unittest.mock import patch, MagicMock
import json

from policyengine_api.constants import (
    MODAL_EXECUTION_STATUS_SUBMITTED,
    MODAL_EXECUTION_STATUS_RUNNING,
    MODAL_EXECUTION_STATUS_COMPLETE,
    MODAL_EXECUTION_STATUS_FAILED,
)

# Mock data constants
MOCK_MODAL_JOB_ID = "fc-abc123xyz"
MOCK_MODAL_BASE_URL = "https://test-modal-api.modal.run"

MOCK_SIMULATION_PAYLOAD = {
    "country": "us",
    "scope": "macro",
    "reform": {"sample_param": {"2024-01-01.2100-12-31": 15}},
    "baseline": {},
    "time_period": "2025",
    "region": "us",
    "data": "gs://policyengine-us-data/cps_2023.h5",
    "include_cliffs": False,
}

MOCK_SIMULATION_RESULT = {
    "poverty_impact": {"baseline": 0.12, "reform": 0.10},
    "budget_impact": {"baseline": 1000, "reform": 1200},
    "inequality_impact": {"baseline": 0.45, "reform": 0.42},
}

MOCK_SUBMIT_RESPONSE_SUCCESS = {
    "job_id": MOCK_MODAL_JOB_ID,
    "status": MODAL_EXECUTION_STATUS_SUBMITTED,
    "poll_url": f"/jobs/{MOCK_MODAL_JOB_ID}",
    "country": "us",
    "version": "1.459.0",
}

MOCK_POLL_RESPONSE_RUNNING = {
    "status": MODAL_EXECUTION_STATUS_RUNNING,
    "result": None,
    "error": None,
}

MOCK_POLL_RESPONSE_COMPLETE = {
    "status": MODAL_EXECUTION_STATUS_COMPLETE,
    "result": MOCK_SIMULATION_RESULT,
    "error": None,
}

MOCK_POLL_RESPONSE_FAILED = {
    "status": MODAL_EXECUTION_STATUS_FAILED,
    "result": None,
    "error": "Simulation timed out",
}

MOCK_HEALTH_RESPONSE = {"status": "healthy"}


def create_mock_httpx_response(
    status_code: int = 200,
    json_data: dict = None,
):
    """
    Helper function to create a mock httpx response.

    Parameters
    ----------
    status_code : int
        HTTP status code for the response.
    json_data : dict
        JSON data to return from response.json().

    Returns
    -------
    MagicMock
        A mock httpx response object.
    """
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = json_data or {}
    mock_response.text = json.dumps(json_data or {})
    mock_response.raise_for_status = MagicMock()

    if status_code >= 400:
        import httpx

        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=mock_response,
        )

    return mock_response


@pytest.fixture
def mock_modal_env_url():
    """Mock the SIMULATION_API_URL environment variable."""
    with patch.dict(
        "os.environ",
        {"SIMULATION_API_URL": MOCK_MODAL_BASE_URL},
    ):
        yield MOCK_MODAL_BASE_URL


@pytest.fixture
def mock_httpx_client():
    """
    Mock httpx.Client for testing SimulationAPIModal.

    Returns a mock client that can be configured for different responses.
    """
    with patch(
        "policyengine_api.libs.simulation_api_modal.httpx.Client"
    ) as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_httpx_client_submit_success(mock_httpx_client):
    """Mock httpx client configured for successful job submission."""
    mock_httpx_client.post.return_value = create_mock_httpx_response(
        status_code=202,
        json_data=MOCK_SUBMIT_RESPONSE_SUCCESS,
    )
    return mock_httpx_client


@pytest.fixture
def mock_httpx_client_poll_running(mock_httpx_client):
    """Mock httpx client configured for polling a running job."""
    mock_httpx_client.get.return_value = create_mock_httpx_response(
        status_code=202,
        json_data=MOCK_POLL_RESPONSE_RUNNING,
    )
    return mock_httpx_client


@pytest.fixture
def mock_httpx_client_poll_complete(mock_httpx_client):
    """Mock httpx client configured for polling a completed job."""
    mock_httpx_client.get.return_value = create_mock_httpx_response(
        status_code=200,
        json_data=MOCK_POLL_RESPONSE_COMPLETE,
    )
    return mock_httpx_client


@pytest.fixture
def mock_httpx_client_poll_failed(mock_httpx_client):
    """Mock httpx client configured for polling a failed job."""
    mock_httpx_client.get.return_value = create_mock_httpx_response(
        status_code=500,
        json_data=MOCK_POLL_RESPONSE_FAILED,
    )
    return mock_httpx_client


@pytest.fixture
def mock_modal_logger():
    """Mock logger for SimulationAPIModal."""
    with patch("policyengine_api.libs.simulation_api_modal.logger") as mock:
        yield mock
