import datetime
import json
from unittest.mock import MagicMock, patch

import pytest
from policyengine_api.constants import (
    MODAL_EXECUTION_STATUS_RUNNING,
    MODAL_EXECUTION_STATUS_SUBMITTED,
)

# Mock data constants
MOCK_COUNTRY_ID = "us"
MOCK_POLICY_ID = 123
MOCK_BASELINE_POLICY_ID = 456
MOCK_REGION = "us"
MOCK_DATASET = (
    "hf://policyengine/faux-populace-us/faux_populace_us_2099.h5@"
    "faux-populace-us-2099-test-release"
)
MOCK_TIME_PERIOD = "2025"
MOCK_API_VERSION = "1.0"
MOCK_OPTIONS = {"option1": "value1", "option2": "value2"}
MOCK_DATA_VERSION = "faux-populace-us-2099-test-release"
MOCK_LOOKUP_OPTIONS_HASH = (
    "[option1=value1&option2=value2"
    "&dataset=hf://policyengine/faux-populace-us/faux_populace_us_2099.h5@"
    "faux-populace-us-2099-test-release"
    "&model_version=1.2.3"
    "&data_version=faux-populace-us-2099-test-release"
    "&policyengine_version=3.4.0]"
)
MOCK_OPTIONS_HASH = (
    MOCK_LOOKUP_OPTIONS_HASH[:-1]
    + "&runtime_app_name=policyengine-simulation-us1-2-3-uk2-7-8]"
)
MOCK_MODAL_JOB_ID = "fc-test123xyz"
MOCK_EXECUTION_ID = MOCK_MODAL_JOB_ID  # Alias for test compatibility
MOCK_RUN_ID = "run-test123xyz"
MOCK_PROCESS_ID = "job_20250626120000_1234"
MOCK_MODEL_VERSION = "1.2.3"
MOCK_POLICYENGINE_VERSION = "3.4.0"
MOCK_RESOLVED_DATASET = MOCK_DATASET
MOCK_RESOLVED_APP_NAME = "policyengine-simulation-us1-2-3-uk2-7-8"
MOCK_RUNTIME_BUNDLE = {
    "model_version": MOCK_MODEL_VERSION,
    "policyengine_version": MOCK_POLICYENGINE_VERSION,
    "data_version": MOCK_DATA_VERSION,
    "dataset": MOCK_RESOLVED_DATASET,
}

MOCK_REFORM_POLICY_JSON = json.dumps({"sample_param": {"2024-01-01.2100-12-31": 15}})

MOCK_BASELINE_POLICY_JSON = json.dumps({})

MOCK_REFORM_IMPACT_DATA = {
    "poverty_impact": {"baseline": 0.12, "reform": 0.10},
    "budget_impact": {"baseline": 1000, "reform": 1200},
    "inequality_impact": {"baseline": 0.45, "reform": 0.42},
}

MOCK_SIM_CONFIG = {
    "country": MOCK_COUNTRY_ID,
    "reform": json.loads(MOCK_REFORM_POLICY_JSON),
    "baseline": json.loads(MOCK_BASELINE_POLICY_JSON),
    "region": MOCK_REGION,
    "time_period": MOCK_TIME_PERIOD,
    "scope": "macro",
    "data": MOCK_RESOLVED_DATASET,
    "include_cliffs": False,
    "model_version": MOCK_MODEL_VERSION,
    "policyengine_version": MOCK_POLICYENGINE_VERSION,
    "data_version": MOCK_DATA_VERSION,
}


@pytest.fixture
def mock_country_package_versions():
    """Mock COUNTRY_PACKAGE_VERSIONS constant."""
    with patch(
        "policyengine_api.services.economy_service.COUNTRY_PACKAGE_VERSIONS",
        {MOCK_COUNTRY_ID: MOCK_MODEL_VERSION},
    ) as mock:
        yield mock


@pytest.fixture
def mock_policyengine_version():
    """Mock the PolicyEngine .py bundle version used by economy routing."""
    with patch(
        "policyengine_api.services.economy_service.POLICYENGINE_VERSION",
        MOCK_POLICYENGINE_VERSION,
    ) as mock:
        yield mock


@pytest.fixture
def mock_policy_service():
    """Mock PolicyService with get_policy_json method."""
    mock_service = MagicMock()
    mock_service.get_policy_json.side_effect = lambda country_id, policy_id: (
        MOCK_REFORM_POLICY_JSON
        if policy_id == MOCK_POLICY_ID
        else MOCK_BASELINE_POLICY_JSON
    )

    with patch(
        "policyengine_api.services.economy_service.policy_service",
        mock_service,
    ) as mock:
        yield mock


@pytest.fixture
def mock_reform_impacts_service():
    """Mock ReformImpactsService with all required methods."""
    mock_service = MagicMock()
    mock_service.get_all_reform_impacts_by_options_hash_prefix.return_value = []
    mock_service.get_all_reform_impacts.return_value = []
    mock_service.set_reform_impact.return_value = None
    mock_service.set_complete_reform_impact.return_value = None
    mock_service.set_error_reform_impact.return_value = None

    with patch(
        "policyengine_api.services.economy_service.reform_impacts_service",
        mock_service,
    ) as mock:
        yield mock


@pytest.fixture
def mock_simulation_api():
    """Mock SimulationAPIModal with all required methods."""
    mock_api = MagicMock()
    mock_execution = create_mock_modal_execution()
    mock_batch_execution = create_mock_budget_window_batch_execution()

    mock_api._setup_sim_options.return_value = MOCK_SIM_CONFIG
    mock_api.run.return_value = mock_execution
    mock_api.resolve_app_name.side_effect = (
        lambda country_id, version=None, policyengine_version=None: (
            MOCK_RESOLVED_APP_NAME,
            version or MOCK_MODEL_VERSION,
        )
    )
    mock_api.get_execution_id.return_value = MOCK_MODAL_JOB_ID
    mock_api.get_execution_by_id.return_value = mock_execution
    mock_api.get_execution_status.return_value = MODAL_EXECUTION_STATUS_RUNNING
    mock_api.get_execution_result.return_value = MOCK_REFORM_IMPACT_DATA
    mock_api.run_budget_window_batch.return_value = mock_batch_execution
    mock_api.get_budget_window_batch_by_id.return_value = mock_batch_execution

    with patch(
        "policyengine_api.services.economy_service.simulation_api", mock_api
    ) as mock:
        yield mock


@pytest.fixture
def mock_budget_window_cache():
    """Mock Redis-backed budget-window cache."""
    mock_cache = MagicMock()
    mock_cache.build_key.return_value = "budget-window-cache-key"
    mock_cache.get_completed_result.return_value = None
    mock_cache.get_batch_job_id.return_value = None
    mock_cache.claim_batch_start.return_value = True
    mock_cache.store_batch_job_id.return_value = None
    mock_cache.clear_starting_claim.return_value = None
    mock_cache.set_completed_result.return_value = None
    mock_cache.clear_batch_job_id.return_value = None

    with patch(
        "policyengine_api.services.economy_service.budget_window_cache",
        mock_cache,
    ) as mock:
        yield mock


@pytest.fixture
def mock_logger():
    """Mock logger."""
    with patch("policyengine_api.services.economy_service.logger") as mock:
        yield mock


@pytest.fixture
def mock_datetime():
    """Mock datetime.datetime.now()."""
    mock_now = datetime.datetime(2025, 6, 26, 12, 0, 0)
    with patch("policyengine_api.services.economy_service.datetime.datetime") as mock:
        mock.now.return_value = mock_now
        yield mock


@pytest.fixture
def mock_numpy_random():
    """Mock numpy random integer generation."""
    with patch(
        "policyengine_api.services.economy_service.np.random.randint",
        return_value=1234,
    ) as mock:
        yield mock


def create_mock_reform_impact(
    status="ok",
    reform_impact_json=None,
    execution_id=MOCK_MODAL_JOB_ID,
    options_hash=MOCK_OPTIONS_HASH,
    start_time=None,
    time_period=MOCK_TIME_PERIOD,
    message=None,
):
    """Helper function to create mock reform impact records."""
    default_reform_impact_json = json.dumps(
        {
            **MOCK_REFORM_IMPACT_DATA,
            "resolved_app_name": MOCK_RESOLVED_APP_NAME,
            "policyengine_bundle": {
                "model_version": MOCK_MODEL_VERSION,
                "policyengine_version": MOCK_POLICYENGINE_VERSION,
                "data_version": MOCK_DATA_VERSION,
                "dataset": MOCK_RESOLVED_DATASET,
            },
        }
    )
    return {
        "id": 1,
        "country_id": MOCK_COUNTRY_ID,
        "policy_id": MOCK_POLICY_ID,
        "baseline_policy_id": MOCK_BASELINE_POLICY_ID,
        "region": MOCK_REGION,
        "dataset": MOCK_RESOLVED_DATASET,
        "time_period": time_period,
        "options_hash": options_hash,
        "status": status,
        "api_version": MOCK_API_VERSION,
        "reform_impact_json": reform_impact_json or default_reform_impact_json,
        "execution_id": execution_id,
        "message": message,
        "start_time": start_time or datetime.datetime(2025, 6, 26, 12, 0, 0),
        "end_time": (
            datetime.datetime(2025, 6, 26, 12, 5, 0) if status == "ok" else None
        ),
    }


def create_mock_modal_execution(
    job_id=MOCK_MODAL_JOB_ID,
    status=MODAL_EXECUTION_STATUS_SUBMITTED,
    result=None,
    error=None,
    policyengine_bundle=None,
):
    """
    Helper function to create mock Modal execution objects.

    Parameters
    ----------
    job_id : str
        The Modal job ID.
    status : str
        The execution status (submitted, running, complete, failed).
    result : dict or None
        The simulation result if complete.
    error : str or None
        The error message if failed.

    Returns
    -------
    MagicMock
        A mock ModalSimulationExecution object.
    """
    mock_execution = MagicMock()
    mock_execution.job_id = job_id
    mock_execution.run_id = MOCK_RUN_ID
    mock_execution.name = job_id  # Alias for compatibility
    mock_execution.status = status
    mock_execution.result = result
    mock_execution.error = error
    mock_execution.policyengine_bundle = policyengine_bundle or MOCK_RUNTIME_BUNDLE
    mock_execution.resolved_app_name = MOCK_RESOLVED_APP_NAME
    return mock_execution


def create_mock_budget_window_batch_execution(
    batch_job_id=MOCK_MODAL_JOB_ID,
    status=MODAL_EXECUTION_STATUS_SUBMITTED,
    progress=None,
    completed_years=None,
    running_years=None,
    queued_years=None,
    failed_years=None,
    result=None,
    error=None,
):
    """Helper function to create mock batch execution objects."""
    mock_execution = MagicMock()
    mock_execution.batch_job_id = batch_job_id
    mock_execution.name = batch_job_id
    mock_execution.status = status
    mock_execution.progress = progress
    mock_execution.completed_years = completed_years or []
    mock_execution.running_years = running_years or []
    mock_execution.queued_years = queued_years or []
    mock_execution.failed_years = failed_years or []
    mock_execution.result = result
    mock_execution.error = error
    return mock_execution


@pytest.fixture
def mock_simulation_api_modal():
    """Mock SimulationAPIModal with all required methods."""
    mock_api = MagicMock()
    mock_execution = create_mock_modal_execution()

    mock_api.run.return_value = mock_execution
    mock_api.resolve_app_name.side_effect = (
        lambda country_id, version=None, policyengine_version=None: (
            MOCK_RESOLVED_APP_NAME,
            version or MOCK_MODEL_VERSION,
        )
    )
    mock_api.get_execution_id.return_value = MOCK_MODAL_JOB_ID
    mock_api.get_execution_by_id.return_value = mock_execution
    mock_api.get_execution_status.return_value = MODAL_EXECUTION_STATUS_RUNNING
    mock_api.get_execution_result.return_value = MOCK_REFORM_IMPACT_DATA

    with patch(
        "policyengine_api.services.economy_service.simulation_api", mock_api
    ) as mock:
        yield mock
