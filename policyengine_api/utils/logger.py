import logging
import sys
from google.cloud import logging as cloud_logging
from datetime import datetime
from pathlib import Path
import os


class Logger:
    def __init__(
        self,
        folder="logs",
        name="api_main",
        log_to_cloud=True,
    ):
        """
        Initialize standard logger

        Three-part filepath:
        - folder (defaults to "logs")
        - name (defaults to "api_main")
        - id (unique identifier for this logging session)

        Args:
            log_to_cloud (bool): Whether to log to Google Cloud Logging
            log_root_dir (str): Directory to store local log files (defaults to "logs")
        """
        # Generate three parts of storage path
        self.folder = folder
        self.name = name
        self.dir = Path(self.folder).joinpath(self.name)
        self.id = datetime.now().strftime("%Y%m%d_%H%M%S")

        self.logger = logging.getLogger(self.name)
        self.logger.setLevel(logging.INFO)

        # Create log directory if it doesn't exist
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(
                f"Warning: Could not create log directory {self.dir}: {str(e)}"
            )
            # Fall back to current directory
            self.dir = Path(".")

        # Create log file path based upon directory
        self.filepath = self.dir.joinpath(f"{self.id}.log")

        self.memory_monitor = None
        self.cloud_client = None
        self.cloud_logger = None

        # Prevent duplicate handlers
        if not self.logger.handlers:
            # File handler - logs to local file
            file_handler = logging.FileHandler(str(self.filepath))
            file_handler.setLevel(logging.INFO)
            file_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
                )
            )
            self.logger.addHandler(file_handler)

            # Console handler
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
                )
            )
            self.logger.addHandler(console_handler)

            # Google Cloud Logging handler; don't log to GCP if in debug
            if log_to_cloud and os.environ.get("FLASK_DEBUG") != "1":
                try:
                    cloud_client = cloud_logging.Client()
                except Exception as e:
                    print(f"Google Cloud Logging error: {str(e)}")
                    return
                cloud_handler = cloud_logging.handlers.CloudLoggingHandler(
                    cloud_client, name=f"{self.name}"
                )
                cloud_handler = cloud_logging.handlers.CloudLoggingHandler(
                    cloud_client
                )
                cloud_handler.setLevel(logging.INFO)
                cloud_handler.setFormatter(
                    logging.Formatter("%(levelname)s - %(message)s")
                )
                self.logger.addHandler(cloud_handler)

    def log(self, message, level="info", **context):
        """
        Log a message with optional context data
        """

        # Format message with context if provided
        if context:
            context_str = " ".join(f"{k}={v}" for k, v in context.items())
            message = f"{message} | {context_str}"

        log_func = getattr(self.logger, level.lower())
        log_func(message)

    def error(self, message, **context):
        """Convenience method to log an error message"""
        self.log(message, level="error", **context)
