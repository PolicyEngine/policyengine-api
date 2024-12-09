import pytest
import os
from unittest.mock import patch, Mock
import logging
from datetime import datetime

TEST_LOGGER_NAME = "test_logger"
TEST_LOGGER_ID = "20240101_120000"


@pytest.fixture(autouse=True)
def mock_flask_debug():
    """
    Fixture to set FLASK_DEBUG=0 for all tests; this is
    necessary because the logger has special behavior in debug
    """
    with patch.dict(os.environ, {"FLASK_DEBUG": "0"}):
        yield


@pytest.fixture(autouse=True)
def clear_handlers():
    """Fixture to clear handlers before each test"""
    logging.getLogger(TEST_LOGGER_NAME).handlers.clear()
    yield
    logging.getLogger(TEST_LOGGER_NAME).handlers.clear()


@pytest.fixture
def temp_log_dir(tmp_path):
    """Fixture to create a temporary log directory"""
    log_dir = tmp_path / "logs"
    log_dir.mkdir(exist_ok=True)  # Create the directory
    return log_dir


@pytest.fixture
def mock_datetime():
    """Fixture to mock datetime for consistent id"""
    with patch("policyengine_api.utils.logger.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2024, 1, 1, 12, 0, 0)
        yield mock_dt


@pytest.fixture
def mock_cloud_logging():
    """Fixture to mock Google Cloud Logging"""
    with patch(
        "policyengine_api.utils.logger.cloud_logging.Client"
    ) as mock_client:
        mock_handler = Mock()
        mock_client.return_value.get_default_handler.return_value = (
            mock_handler
        )
        yield mock_client
