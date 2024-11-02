import logging
import sys
from rq import Worker, get_current_job
from google.cloud import logging as cloud_logging
from datetime import datetime


class WorkerLogger:
    @staticmethod
    def get_worker_id():
        """
        Attempts to get the worker ID through various methods:
        1. From current RQ job
        2. From environment variable
        3. From RQ worker name
        4. Generates a default if none found
        """
        # Try to get from current job context
        current_job = get_current_job()
        if current_job and current_job.worker_name:
            return current_job.worker_name

        # Try to get from current worker
        try:
            worker = Worker.find_by_key(
                Worker.worker_key_prefix + current_job.worker_name
            )
            if worker:
                return worker.name
        except:
            pass

        # Default to timestamp if no other ID found
        return f'worker_{datetime.now().strftime("%Y%m%d_%H%M%S")}'

    def __init__(self, worker_id=None, log_to_cloud=True):
        """
        Initialize logger with automatic worker ID detection if none provided
        """
        self.worker_id = worker_id or self.get_worker_id()
        self.logger = logging.getLogger(f"worker_{self.worker_id}")
        self.logger.setLevel(logging.INFO)

        # Prevent duplicate handlers
        if not self.logger.handlers:
            # File handler - logs to local file
            file_handler = logging.FileHandler(
                f"logs/worker_{self.worker_id}.log"
            )
            file_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
                )
            )
            self.logger.addHandler(file_handler)

            # Console handler
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
                )
            )
            self.logger.addHandler(console_handler)

            # Google Cloud Logging handler
            if log_to_cloud:
                cloud_client = cloud_logging.Client()
                cloud_handler = cloud_logging.handlers.CloudLoggingHandler(
                    cloud_client, name=f"worker_{self.worker_id}"
                )
                cloud_handler.setFormatter(
                    logging.Formatter("%(levelname)s - %(message)s")
                )
                self.logger.addHandler(cloud_handler)

    def log(self, message, level="info", **context):
        """
        Log a message with optional context data
        """
        # Add job ID to context if available
        current_job = get_current_job()
        if current_job:
            context["job_id"] = current_job.id

        # Format message with context if provided
        if context:
            context_str = " ".join(f"{k}={v}" for k, v in context.items())
            message = f"{message} | {context_str}"

        log_func = getattr(self.logger, level.lower())
        log_func(message)
