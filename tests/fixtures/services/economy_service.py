import pytest
from unittest.mock import patch, MagicMock
import json
import datetime

from policyengine_api.constants import (
    MODAL_EXECUTION_STATUS_SUBMITTED,
    MODAL_EXECUTION_STATUS_RUNNING,
)

# Mock data constants
MOCK_COUNTRY_ID = "us"
MOCK_POLICY_ID = 123
MOCK_BASELINE_POLICY_ID = 456
MOCK_REGION = "us"
MOCK_DATASET = "enhanced_cps"
MOCK_TIME_PERIOD = "2025"
MOCK_API_VERSION = "1.0"
MOCK_OPTIONS = {"option1": "value1", "option2": "value2"}
MOCK_OPTIONS_HASH = "[option1=value1&option2=value2]"
MOCK_MODAL_JOB_ID = "fc-test123xyz"
MOCK_EXECUTION_ID = MOCK_MODAL_JOB_ID  # Alias for test compatibility
MOCK_PROCESS_ID = "job_20250626120000_1234"
MOCK_MODEL_VERSION = "1.2.3"
MOCK_DATA_VERSION = None

MOCK_REFORM_POLICY_JSON = json.dumps(
    {"sample_param": {"2024-01-01.2100-12-31": 15}}
)

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
    "dataset": MOCK_DATASET,
    "include_cliffs": False,
    "model_version": MOCK_MODEL_VERSION,
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
def mock_get_dataset_version():
    """Mock get_dataset_version function."""
    with patch(
        "policyengine_api.services.economy_service.get_dataset_version",
        return_value=MOCK_DATA_VERSION,
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

    mock_api._setup_sim_options.return_value = MOCK_SIM_CONFIG
    mock_api.run.return_value = mock_execution
    mock_api.get_execution_id.return_value = MOCK_MODAL_JOB_ID
    mock_api.get_execution_by_id.return_value = mock_execution
    mock_api.get_execution_status.return_value = MODAL_EXECUTION_STATUS_RUNNING
    mock_api.get_execution_result.return_value = MOCK_REFORM_IMPACT_DATA

    with patch(
        "policyengine_api.services.economy_service.simulation_api", mock_api
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
    with patch(
        "policyengine_api.services.economy_service.datetime.datetime"
    ) as mock:
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
    status="ok", reform_impact_json=None, execution_id=MOCK_MODAL_JOB_ID
):
    """Helper function to create mock reform impact records."""
    return {
        "id": 1,
        "country_id": MOCK_COUNTRY_ID,
        "policy_id": MOCK_POLICY_ID,
        "baseline_policy_id": MOCK_BASELINE_POLICY_ID,
        "region": MOCK_REGION,
        "dataset": MOCK_DATASET,
        "time_period": MOCK_TIME_PERIOD,
        "options_hash": MOCK_OPTIONS_HASH,
        "status": status,
        "api_version": MOCK_API_VERSION,
        "reform_impact_json": reform_impact_json
        or json.dumps(MOCK_REFORM_IMPACT_DATA),
        "execution_id": execution_id,
        "start_time": datetime.datetime(2025, 6, 26, 12, 0, 0),
        "end_time": (
            datetime.datetime(2025, 6, 26, 12, 5, 0)
            if status == "ok"
            else None
        ),
    }


def create_mock_modal_execution(
    job_id=MOCK_MODAL_JOB_ID,
    status=MODAL_EXECUTION_STATUS_SUBMITTED,
    result=None,
    error=None,
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
    mock_execution.name = job_id  # Alias for compatibility
    mock_execution.status = status
    mock_execution.result = result
    mock_execution.error = error
    return mock_execution


@pytest.fixture
def mock_simulation_api_modal():
    """Mock SimulationAPIModal with all required methods."""
    mock_api = MagicMock()
    mock_execution = create_mock_modal_execution()

    mock_api.run.return_value = mock_execution
    mock_api.get_execution_id.return_value = MOCK_MODAL_JOB_ID
    mock_api.get_execution_by_id.return_value = mock_execution
    mock_api.get_execution_status.return_value = MODAL_EXECUTION_STATUS_RUNNING
    mock_api.get_execution_result.return_value = MOCK_REFORM_IMPACT_DATA

    with patch(
        "policyengine_api.services.economy_service.simulation_api", mock_api
    ) as mock:
        yield mock


# Expected GCS paths from get_default_dataset
MOCK_US_NATIONWIDE_DATASET = "gs://policyengine-us-data/cps_2023.h5"
MOCK_US_STATE_CA_DATASET = "gs://policyengine-us-data/states/CA.h5"
MOCK_US_STATE_UT_DATASET = "gs://policyengine-us-data/states/UT.h5"
MOCK_US_PLACE_NJ_57000_DATASET = "gs://policyengine-us-data/states/NJ.h5"
MOCK_US_DISTRICT_CA37_DATASET = "gs://policyengine-us-data/districts/CA-37.h5"
MOCK_UK_DATASET = "gs://policyengine-uk-data-private/enhanced_frs_2023_24.h5"


def mock_get_default_dataset_fn(country: str, region: str | None) -> str:
    """Mock implementation of get_default_dataset for testing."""
    if country == "uk":
        return MOCK_UK_DATASET
    elif country == "us":
        if region == "us" or region is None:
            return MOCK_US_NATIONWIDE_DATASET
        elif region == "state/ca":
            return MOCK_US_STATE_CA_DATASET
        elif region == "state/ut":
            return MOCK_US_STATE_UT_DATASET
        elif region.startswith("place/"):
            # Place uses parent state's dataset
            place_code = region.split("/")[1]
            state_abbrev = place_code.split("-")[0].upper()
            return f"gs://policyengine-us-data/states/{state_abbrev}.h5"
        elif region == "congressional_district/CA-37":
            return MOCK_US_DISTRICT_CA37_DATASET
        elif region.startswith("state/"):
            # Generic state handling
            state_code = region.split("/")[1].upper()
            return f"gs://policyengine-us-data/states/{state_code}.h5"
        elif region.startswith("congressional_district/"):
            district_id = region.split("/")[1].upper()
            return f"gs://policyengine-us-data/districts/{district_id}.h5"
        else:
            return MOCK_US_NATIONWIDE_DATASET
    raise ValueError(f"Unknown country: {country}")


@pytest.fixture
def mock_get_default_dataset():
    """Mock get_default_dataset function."""
    with patch(
        "policyengine_api.services.economy_service.get_default_dataset",
        side_effect=mock_get_default_dataset_fn,
    ) as mock:
        yield mock
