import pytest
import logging
from pathlib import Path
import os
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from google.cloud import logging as cloud_logging
from policyengine_api.utils.logger import Logger

from tests.fixtures.logging_fixtures import (
    mock_flask_debug,
    clear_handlers,
    temp_log_dir,
    mock_datetime,
    mock_cloud_logging,
    TEST_LOGGER_NAME,
    TEST_LOGGER_ID,
)


class TestLogger:
    def test_logger_initialization(self, temp_log_dir, mock_datetime):
        """Test basic logger initialization"""
        logger = Logger(
            folder=str(temp_log_dir), name=TEST_LOGGER_NAME, log_to_cloud=False
        )

        # Check if logger was properly initialized
        assert logger.name == TEST_LOGGER_NAME
        assert logger.id == TEST_LOGGER_ID
        assert logger.logger.level == logging.INFO

        # Verify log directory creation
        expected_log_dir = temp_log_dir / TEST_LOGGER_NAME
        assert expected_log_dir.exists()

        # Verify log file creation
        expected_log_file = expected_log_dir / (TEST_LOGGER_ID + ".log")
        assert expected_log_file.exists()

    def test_logger_handlers(self, temp_log_dir):
        """Test that appropriate handlers are added"""
        logger = Logger(
            folder=str(temp_log_dir), name=TEST_LOGGER_NAME, log_to_cloud=False
        )

        # Should have exactly 2 handlers (file and console) when cloud logging is disabled
        assert len(logger.logger.handlers) == 2

        # Verify handler types
        handlers = logger.logger.handlers
        assert any(isinstance(h, logging.FileHandler) for h in handlers)
        assert any(isinstance(h, logging.StreamHandler) for h in handlers)

    def test_cloud_logging_initialization(
        self, temp_log_dir, mock_cloud_logging
    ):
        """Test initialization with cloud logging enabled"""
        logger = Logger(
            folder=str(temp_log_dir), name=TEST_LOGGER_NAME, log_to_cloud=True
        )

        # Should have 3 handlers (file, console, and cloud)
        assert len(logger.logger.handlers) == 3
        mock_cloud_logging.assert_called_once()

    def test_log_message(self, temp_log_dir, mock_datetime):
        """Test logging a message"""
        logger = Logger(
            folder=str(temp_log_dir), name=TEST_LOGGER_NAME, log_to_cloud=False
        )

        test_message = "Test log message"
        logger.log(test_message)

        # Read the log file and verify the message was logged
        log_file = temp_log_dir / TEST_LOGGER_NAME / (TEST_LOGGER_ID + ".log")
        assert log_file.exists(), f"Log file not found at {log_file}"
        with open(log_file, "r") as f:
            log_content = f.read()
        assert test_message in log_content

    def test_log_with_context(self, temp_log_dir, mock_datetime):
        """Test logging a message with context"""
        logger = Logger(
            folder=str(temp_log_dir), name=TEST_LOGGER_NAME, log_to_cloud=False
        )

        test_message = "Test message"
        context = {"user": "test_user", "action": "login"}
        logger.log(test_message, **context)

        # Read the log file and verify the message and context were logged
        log_file = temp_log_dir / TEST_LOGGER_NAME / (TEST_LOGGER_ID + ".log")
        assert log_file.exists(), f"Log file not found at {log_file}"
        with open(log_file, "r") as f:
            log_content = f.read()
        assert test_message in log_content
        assert "user=test_user" in log_content
        assert "action=login" in log_content

    def test_error_logging(self, temp_log_dir, mock_datetime):
        """Test error logging functionality"""
        logger = Logger(
            folder=str(temp_log_dir), name=TEST_LOGGER_NAME, log_to_cloud=False
        )

        error_message = "Test error message"
        logger.error(error_message)

        # Use the exact log file path based on the mocked datetime
        log_file = temp_log_dir / TEST_LOGGER_NAME / (TEST_LOGGER_ID + ".log")
        assert log_file.exists(), f"Log file not found at {log_file}"

        with open(log_file, "r") as f:
            log_content = f.read()
        assert (
            error_message in log_content
        ), "Error message not found in log content"
        assert "ERROR" in log_content, "ERROR level not found in log content"

    def test_debug_mode_behavior(self, temp_log_dir):
        """Test logger behavior in debug mode"""
        with patch.dict(os.environ, {"FLASK_DEBUG": "1"}):
            logger = Logger(
                folder=str(temp_log_dir),
                name=TEST_LOGGER_NAME,
                log_to_cloud=False,
            )
            # Logger should not be initialized in debug mode
            assert not hasattr(logger, "logger")

    def test_failed_directory_creation(self, temp_log_dir, mock_datetime):
        """Test fallback behavior when log directory creation fails"""
        with patch("pathlib.Path.mkdir") as mock_mkdir:
            mock_mkdir.side_effect = PermissionError("Permission denied")

            logger = Logger(
                folder=str(temp_log_dir),
                name=TEST_LOGGER_NAME,
                log_to_cloud=False,
            )

            # Should fallback to current directory
            assert logger.dir == Path(".")
