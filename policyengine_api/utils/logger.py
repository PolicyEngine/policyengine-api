import logging
import sys
from rq import Worker, get_current_job
from google.cloud import logging as cloud_logging
from datetime import datetime
import time
import threading
import psutil
from typing import Optional
from pathlib import Path
import os
from weakref import proxy
import signal


class Logger:
    def __init__(
        self,
        logger_root_dir="logs",
        logger_name="default",
        log_to_cloud=True,
    ):
        """
        Initialize standard logger

        Three-part filepath:
        - log_dir (defaults to "logs")
        - logger_name (defaults to "default")
        - logger_id (unique identifier for this logging session)

        Args:
            log_to_cloud (bool): Whether to log to Google Cloud Logging
            log_root_dir (str): Directory to store local log files (defaults to "logs")
        """
        # Check if running in debug; if so, don't initialize before Werkzeug,
        # otherwise we'll generate two log files, one which will be empty
        if os.environ.get("FLASK_DEBUG") == "1" and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
            print("Skipping logger initialization in debug mode pre-Werkzeug")
            return

        self.logger_root_dir = logger_root_dir
        self.logger_name = logger_name
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(logging.INFO)

        # Generate a unique ID based on time
        self.logger_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Create log directory if it doesn't exist
        self.logger_full_dir = Path(self.logger_root_dir).joinpath(logger_name)
        try:
            self.logger_full_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(
                f"Warning: Could not create log directory {self.logger_full_dir}: {str(e)}"
            )
            # Fall back to current directory
            self.log_dir = Path(".")

        self.memory_monitor = None
        self.cloud_client = None
        self.cloud_logger = None
        print(f"Initialized logger")

        # Prevent duplicate handlers
        if not self.logger.handlers:
            # File handler - logs to local file
            self.log_file = self.logger_full_dir / f"{self.logger_id}.log"
            file_handler = logging.FileHandler(str(self.log_file))
            file_handler.setLevel(logging.INFO)
            print(f"Logging to file: logs/{self.logger_name}/{self.logger_id}.log")
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
                    cloud_client, name=f"{self.logger_name}"
                )
                cloud_handler = cloud_logging.handlers.CloudLoggingHandler(cloud_client)
                cloud_handler.setLevel(logging.INFO)
                cloud_handler.setFormatter(
                    logging.Formatter("%(levelname)s - %(message)s")
                )
                self.logger.addHandler(cloud_handler)

    def log(self, message, level="info", **context):
        """
        Log a message with optional context data
        """

        # Don't log if running in debug and Werkzeug not initialized;
        # this will prevent duplicate log files
        if getattr(self, "logger", None) is None:
            print("Logger not initialized; skipping log")
            return

        # Format message with context if provided
        if context:
            context_str = " ".join(f"{k}={v}" for k, v in context.items())
            message = f"{message} | {context_str}"

        log_func = getattr(self.logger, level.lower())
        log_func(message)


# class WorkerLogger:
#     @staticmethod
#     def get_worker_id():
#         """
#         Attempts to get the worker ID through various methods:
#         1. From current RQ job
#         2. From environment variable
#         3. From RQ worker name
#         4. Generates a default if none found
#         """
#         # Try to get from current job context
#         current_job = get_current_job()
#         if current_job and current_job.worker_name:
#             return current_job.worker_name
# 
#         # Try to get from current worker
#         try:
#             worker = Worker.find_by_key(
#                 Worker.worker_key_prefix + current_job.worker_name
#             )
#             if worker:
#                 return worker.name
#         except:
#             pass
# 
#         # Default to timestamp if no other ID found
#         return datetime.now().strftime("%Y%m%d_%H%M%S")
# 
#     def __init__(
#         self,
#         worker_id=None,
#         job_id=None,
#         log_to_cloud=True,
#         log_dir="logs",
#         monitor_memory=True,
#         memory_threshold=75,
#         memory_check_interval=5,
#     ):
#         """
#         Initialize logger with automatic worker ID detection if none provided
# 
#         Args:
#             worker_id (str): Optional worker ID
#             log_to_cloud (bool): Whether to log to Google Cloud Logging
#             log_dir (str): Directory to store local log files (defaults to "logs")
#             monitor_memory (bool): Whether to monitor memory usage
#             memory_threshold (int): Memory usage threshold to trigger warnings (default: 90%)
#             memory_check_interval (int): How often to check memory in seconds (default: 5)
#         """
#         self.worker_id = worker_id or self.get_worker_id()
#         self.logger = logging.getLogger(f"worker_{self.worker_id}")
#         self.logger.setLevel(logging.INFO)
# 
#         self.log_dir = Path(log_dir)
# 
#         # Create log directory if it doesn't exist
#         self.log_dir = Path(log_dir)
#         try:
#             self.log_dir.mkdir(parents=True, exist_ok=True)
#         except Exception as e:
#             print(
#                 f"Warning: Could not create log directory {log_dir}: {str(e)}"
#             )
#             # Fall back to current directory
#             self.log_dir = Path(".")
# 
#         self.memory_monitor = None
#         if monitor_memory:
#             self.memory_monitor = MemoryMonitor(
#                 logger=self,
#                 threshold_percent=memory_threshold,
#                 check_interval=memory_check_interval,
#             )
# 
#         self.cloud_client = None
#         self.cloud_logger = None
#         print(f"Initialized worker logger with ID: {self.worker_id}")
# 
#         # Prevent duplicate handlers
#         if not self.logger.handlers:
#             # File handler - logs to local file
#             log_file = self.log_dir / f"worker_{self.worker_id}.log"
#             file_handler = logging.FileHandler(str(log_file))
#             print(f"Logging to file: logs/worker_{self.worker_id}.log")
#             file_handler.setFormatter(
#                 logging.Formatter(
#                     "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
#                 )
#             )
#             self.logger.addHandler(file_handler)
# 
#             # Console handler
#             console_handler = logging.StreamHandler(sys.stdout)
#             console_handler.setFormatter(
#                 logging.Formatter(
#                     "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
#                 )
#             )
#             self.logger.addHandler(console_handler)
# 
#             # Google Cloud Logging handler
#             if log_to_cloud:
#                 cloud_client = cloud_logging.Client()
#                 cloud_handler = cloud_logging.handlers.CloudLoggingHandler(
#                     cloud_client, name=f"worker_{self.worker_id}"
#                 )
#                 cloud_handler.setFormatter(
#                     logging.Formatter("%(levelname)s - %(message)s")
#                 )
#                 self.logger.addHandler(cloud_handler)
# 
#     def log(self, message, level="info", **context):
#         """
#         Log a message with optional context data
#         """
#         # Add job ID to context if available
#         current_job = get_current_job()
#         if current_job:
#             context["job_id"] = current_job.id
# 
#         # Format message with context if provided
#         if context:
#             context_str = " ".join(f"{k}={v}" for k, v in context.items())
#             message = f"{message} | {context_str}"
# 
#         log_func = getattr(self.logger, level.lower())
#         log_func(message)
# 
#     def log_memory_stats(
#         self, process_memory_mb, process_percent, system_percent
#     ):
#         """Log memory statistics"""
#         self.log(
#             "Memory usage stats",
#             level="info",
#             metric_type="memory_usage",
#             process_memory_mb=round(process_memory_mb, 2),
#             process_percent=round(process_percent, 2),
#             system_percent=round(system_percent, 2),
#         )
# 
#     def log_memory_warning(self, message, **context):
#         """Log memory warning"""
#         self.log(
#             message, level="warning", metric_type="memory_warning", **context
#         )
# 
#     def __enter__(self):
#         """Context manager entry"""
#         return self
# 
#     def __exit__(self, exc_type, exc_val, exc_tb):
#         """Context manager exit - ensure cleanup"""
#         if self.memory_monitor:
#             self.memory_monitor.stop()
# 
# 
# class MemoryMonitor:
#     def __init__(self, threshold_percent=90, check_interval=5, logger=None):
#         """
#         Initialize memory monitor
# 
#         Args:
#             threshold_percent (int): Memory usage threshold to trigger warnings (default: 75%)
#             check_interval (int): How often to check memory in seconds (default: 5)
#         """
#         self.threshold_percent = threshold_percent
#         self.check_interval = check_interval
#         self.stop_flag = threading.Event()
#         self.monitor_thread: Optional[threading.Thread] = None
#         self.logger = proxy(logger)
#         self._pid = os.getpid()
# 
#     def start(self):
#         """Start memory monitoring in a separate thread"""
#         self.stop_flag.clear()
#         self._pid = os.getpid()
# 
#         self.monitor_thread = threading.Thread(target=self._monitor_memory)
#         self.monitor_thread.daemon = True
#         self.monitor_thread.start()
# 
#         self._setup_signal_handlers()
# 
#     def stop(self):
#         """Stop memory monitoring"""
#         if self.monitor_thread and self.monitor_thread.is_alive():
#             self.stop_flag.set()
#             self.monitor_thread.join(timeout=1.0)
# 
#     def _setup_signal_handlers(self):
#         """Setup signal handlers to stop monitoring"""
# 
#         for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGQUIT):
#             signal.signal(sig, self._handle_signal)
# 
#     def _handle_signal(self, signum, frame):
#         """Signal handler to stop monitoring"""
#         self.logger.log(
#             f"Received signal {signum}, stopping memory monitor",
#             level="critical",
#         )
#         self.stop()
# 
#     def _monitor_memory(self):
#         """Memory monitoring loop"""
#         process = psutil.Process()
#         while not self.stop_flag.is_set():
#             try:
# 
#                 if os.getpid() != self._pid:
#                     self.logger.log(
#                         "Memory monitor detected PID mismatch, stopping",
#                         level="warning",
#                     )
#                     break
# 
#                 try:
#                     process = psutil.Process(self._pid)
#                 except psutil.NoSuchProcess:
#                     self.logger.log(
#                         "Memory monitor detected missing process, stopping",
#                         level="warning",
#                     )
#                     break
# 
#                 if not process.is_running():
#                     self.logger.log(
#                         "Memory monitor detected process stopped, stopping",
#                         level="warning",
#                     )
#                     break
# 
#                 try:
#                     # Get memory info
#                     memory_info = process.memory_info()
#                     system_memory = psutil.virtual_memory()
#                 except Exception as e:
#                     self.logger.log(
#                         f"Error getting memory info: {str(e)}",
#                         level="error",
#                         error_type=type(e).__name__,
#                     )
#                     break
# 
#                 # Calculate usage percentages
#                 process_percent = (memory_info.rss / system_memory.total) * 100
#                 system_percent = system_memory.percent
# 
#                 # Log memory stats
#                 self.logger.log_memory_stats(
#                     process_memory_mb=memory_info.rss / (1024 * 1024),
#                     process_percent=process_percent,
#                     system_percent=system_percent,
#                 )
# 
#                 # Check for high memory usage
#                 if system_percent > self.threshold_percent:
#                     self.logger.log_memory_warning(
#                         f"High system memory usage: {system_percent:.1f}%",
#                         system_percent=system_percent,
#                     )
# 
#                 if process_percent > (
#                     self.threshold_percent / 2
#                 ):  # Process threshold at half of system
#                     self.logger.log_memory_warning(
#                         f"High process memory usage: {process_percent:.1f}%",
#                         process_percent=process_percent,
#                     )
# 
#             except Exception as e:
#                 self.logger.log(
#                     f"Error monitoring memory: {str(e)}",
#                     level="error",
#                     error_type=type(e).__name__,
#                 )
# 
#             time.sleep(self.check_interval)