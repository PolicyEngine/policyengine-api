"""Test fixtures for SimulationAPIModal.

This module provides mock data, fixtures, and helper functions for testing
the Modal simulation API client.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from policyengine_api.constants import (
    MODAL_EXECUTION_STATUS_COMPLETE,
    MODAL_EXECUTION_STATUS_FAILED,
    MODAL_EXECUTION_STATUS_RUNNING,
    MODAL_EXECUTION_STATUS_SUBMITTED,
)
from tests.fixtures.spm import (
    worker_result_fields,
    worker_spm_capability,
    worker_versions_document,
)

# Mock data constants
MOCK_MODAL_JOB_ID = "fc-abc123xyz"
MOCK_OBSERVABILITY_ID = "00000000-0000-4000-8000-000000000001"
MOCK_BATCH_JOB_ID = "fc-batch123xyz"
MOCK_MODAL_BASE_URL = "https://test-modal-api.modal.run"

MOCK_SIMULATION_PAYLOAD = {
    "country": "us",
    "scope": "macro",
    "reform": {"sample_param": {"2024-01-01.2100-12-31": 15}},
    "baseline": {},
    "time_period": "2025",
    "region": "us",
    "include_cliffs": False,
}

MOCK_SIMULATION_PAYLOAD_WITH_TELEMETRY = {
    **MOCK_SIMULATION_PAYLOAD,
    "_telemetry": {
        "submission_claim_id": "job_20250626120000_1234",
        "capture_mode": "disabled",
    },
}

MOCK_SIMULATION_RESULT = {
    "poverty_impact": {"baseline": 0.12, "reform": 0.10},
    "budget_impact": {"baseline": 1000, "reform": 1200},
    "inequality_impact": {"baseline": 0.45, "reform": 0.42},
    **worker_result_fields(years=["2025"]),
}
# The simulation API's LocalAreaBreakdownOutput for a breakdown=local_areas run.
MOCK_LOCAL_AREA_BREAKDOWN_RESULT = {
    "kind": "local_areas",
    "model_version": "2.132.6",
    "policyengine_version": "6.10.0",
    "dataset": "microcosm_uk_2024_25_dense",
    "data_version": "microcosm-uk-2024-25-dense-test-release",
    "constituency_impact": [
        {
            "constituency_code": "E14001063",
            "constituency_name": "Aldershot",
            "x": 10,
            "y": 20,
            "average_household_income_change": 120.0,
            "relative_household_income_change": 0.003,
            "population": 41000.0,
            "disclosure_tier": "reported",
        }
    ],
    "local_authority_impact": [
        {
            "local_authority_code": "E07000092",
            "local_authority_name": "Rushmoor",
            "x": 3,
            "y": 7,
            "average_household_income_change": 110.0,
            "relative_household_income_change": 0.0028,
            "population": 39000.0,
            "disclosure_tier": "approximate",
        }
    ],
}
# The same result from a simulation API that lists, for each level, the ONS
# codes of the areas the run estimated but disclosure control withheld, sorted
# (PolicyEngine/policyengine-sim-api#968). An empty list means none were.
MOCK_LOCAL_AREA_BREAKDOWN_RESULT_WITH_WITHHELD_CODES = {
    **MOCK_LOCAL_AREA_BREAKDOWN_RESULT,
    "constituency_withheld_codes": ["E14001172", "S14000021"],
    "local_authority_withheld_codes": [],
}
# A result that doesn't report its withheld areas, with null for each level.
MOCK_LOCAL_AREA_BREAKDOWN_RESULT_WITH_NULL_WITHHELD_CODES = {
    **MOCK_LOCAL_AREA_BREAKDOWN_RESULT,
    "constituency_withheld_codes": None,
    "local_authority_withheld_codes": None,
}
MOCK_POLICYENGINE_BUNDLE = {
    "model_version": "1.459.0",
    "policyengine_version": "3.4.0",
    "data_version": "faux-populace-us-2099-test-release",
    "dataset": (
        "hf://policyengine/faux-populace-us/faux_populace_us_2099.h5@"
        "faux-populace-us-2099-test-release"
    ),
}
MOCK_RESOLVED_APP_NAME = "policyengine-us-1-459-0"
MOCK_WORKER_VERSIONS = worker_versions_document(
    app_name=MOCK_RESOLVED_APP_NAME,
    country_version="1.459.0",
)
for bundle_version in ("3.4.0", "4.18.3"):
    MOCK_WORKER_VERSIONS["policyengine"][bundle_version] = MOCK_RESOLVED_APP_NAME
    MOCK_WORKER_VERSIONS["spm_capabilities"][bundle_version] = worker_spm_capability()

MOCK_SUBMIT_RESPONSE_SUCCESS = {
    "job_id": MOCK_MODAL_JOB_ID,
    "status": MODAL_EXECUTION_STATUS_SUBMITTED,
    "poll_url": f"/jobs/{MOCK_MODAL_JOB_ID}",
    "country": "us",
    "version": "1.459.0",
    "policyengine_bundle": MOCK_POLICYENGINE_BUNDLE,
    "resolved_app_name": MOCK_RESOLVED_APP_NAME,
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
    "policyengine_bundle": MOCK_POLICYENGINE_BUNDLE,
    "resolved_app_name": MOCK_RESOLVED_APP_NAME,
}

MOCK_POLL_RESPONSE_FAILED = {
    "status": MODAL_EXECUTION_STATUS_FAILED,
    "result": None,
    "error": "Simulation timed out",
}

MOCK_HEALTH_RESPONSE = {"status": "healthy"}

MOCK_BATCH_SUBMIT_RESPONSE_SUCCESS = {
    "batch_job_id": MOCK_BATCH_JOB_ID,
    "status": MODAL_EXECUTION_STATUS_SUBMITTED,
    "poll_url": f"/budget-window-jobs/{MOCK_BATCH_JOB_ID}",
    "country": "us",
    "version": "1.459.0",
}

MOCK_BATCH_POLL_RESPONSE_RUNNING = {
    "status": MODAL_EXECUTION_STATUS_RUNNING,
    "progress": 33,
    "completed_years": ["2026"],
    "running_years": ["2027"],
    "queued_years": ["2028"],
    "failed_years": [],
    "result": None,
    "error": None,
}

MOCK_BATCH_POLL_RESPONSE_COMPLETE = {
    "status": MODAL_EXECUTION_STATUS_COMPLETE,
    "progress": 100,
    "completed_years": ["2026", "2027", "2028"],
    "running_years": [],
    "queued_years": [],
    "failed_years": [],
    "result": {
        "kind": "budgetWindow",
        "startYear": "2026",
        "endYear": "2028",
        "windowSize": 3,
        "annualImpacts": [
            {
                "year": year,
                **MOCK_SIMULATION_RESULT,
                **worker_result_fields(years=[year]),
            }
            for year in ("2026", "2027", "2028")
        ],
        "totals": {},
    },
    "error": None,
}

MOCK_BATCH_POLL_RESPONSE_FAILED = {
    "status": MODAL_EXECUTION_STATUS_FAILED,
    "progress": 33,
    "completed_years": ["2026"],
    "running_years": [],
    "queued_years": ["2028"],
    "failed_years": ["2027"],
    "result": None,
    "error": "Budget window failed",
}


def create_mock_httpx_response(
    status_code: int = 200,
    json_data: dict | None = None,
    headers: dict | None = None,
):
    """Build a mock httpx response for the Simulation Entrypoint client tests.

    Parameters
    ----------
    status_code : int
        HTTP status code for the response.
    json_data : dict
        JSON data to return from response.json().
    headers : dict or None
        Response headers; defaults to a mock observability-id header.

    Returns
    -------
    MagicMock
        A mock httpx response object.

    """
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.headers = headers or {
        "X-PolicyEngine-Observability-Id": MOCK_OBSERVABILITY_ID
    }
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
    """Mock the SIMULATION_ENTRYPOINT_URL environment variable."""
    with patch.dict(
        "os.environ",
        {"SIMULATION_ENTRYPOINT_URL": MOCK_MODAL_BASE_URL},
    ):
        yield MOCK_MODAL_BASE_URL


@pytest.fixture
def mock_httpx_client():
    """Mock httpx.Client for testing SimulationAPIModal.

    Returns a mock client that can be configured for different responses.
    """
    with patch(
        "policyengine_api.libs.simulation_entrypoint.httpx.Client"
    ) as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get.return_value = create_mock_httpx_response(
            status_code=200,
            json_data=MOCK_WORKER_VERSIONS,
        )
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
    with patch("policyengine_api.libs.simulation_entrypoint.logger") as mock:
        yield mock
