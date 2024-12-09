from policyengine_api.utils.logger import Logger
from rq import Worker, get_current_job
from datetime import datetime
import time
import threading
import psutil
from typing import Optional
import os
from weakref import proxy
import signal


class WorkerLogger(Logger):
    """
    Custom logger for worker processes
    """

    def __init__(
        self,
        dir: str = "logs",
        name: str = "worker",
        id: str = None,
        log_to_cloud: bool = True,
        monitor_memory: bool = True,
        memory_threshold: int = 75,
        memory_check_interval: int = 5,
    ):
        """
        Initialize logger with automatic worker ID detection if none provided

        All args optional
        Args:
            dir (str): Directory to store log files (defaults to "logs")
            name (str): Name of the logger (defaults to "worker")
            id (str): ID to append to log file name; if not provided, will fetch worker name
            log_to_cloud (bool): Whether to log to Google Cloud Logging (defaults to True)
            monitor_memory (bool): Whether to monitor memory usage (defaults to True)
            memory_threshold (int): Memory usage threshold to trigger warnings (default: 75%)
            memory_check_interval (int): How often to check memory in seconds (default: 5)
        """
        self.dir = dir
        self.name = name
        self.log_to_cloud = log_to_cloud

        if id is not None:
            self.id = id
        else:
            self.id = self.get_worker_id()

        super().__init__(
            dir=self.dir,
            name=self.name,
            id=self.id,
            log_to_cloud=self.log_to_cloud,
        )

        self.memory_monitor: MemoryMonitor = None
        if monitor_memory:
            self.memory_monitor = MemoryMonitor(
                logger=self,
                threshold_percent=memory_threshold,
                check_interval=memory_check_interval,
            )

        print(f"Initialized worker logger with ID: {self.id}")

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
        return datetime.now().strftime("%Y%m%d_%H%M%S")


class MemoryMonitor:
    def __init__(self, threshold_percent=90, check_interval=5, logger=None):
        """
        Initialize memory monitor

        Args:
            threshold_percent (int): Memory usage threshold to trigger warnings (default: 75%)
            check_interval (int): How often to check memory in seconds (default: 5)
        """
        self.threshold_percent: int = threshold_percent
        self.check_interval: int = check_interval
        self.stop_flag = threading.Event()
        self.monitor_thread: Optional[threading.Thread] = None
        self.logger: Logger = proxy(logger)
        self._pid: int = os.getpid()

    def start(self):
        """Start memory monitoring in a separate thread"""
        self.stop_flag.clear()
        self._pid = os.getpid()

        self.monitor_thread = threading.Thread(target=self._monitor_memory)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()

        self._setup_signal_handlers()

    def stop(self):
        """Stop memory monitoring"""
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.stop_flag.set()
            self.monitor_thread.join(timeout=1.0)

    def _setup_signal_handlers(self):
        """Setup signal handlers to stop monitoring"""

        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGQUIT):
            signal.signal(sig, self._handle_signal)

    def _handle_signal(self, signum: signal):
        """Signal handler to stop monitoring"""
        self.logger.log(
            f"Received signal {signum}, stopping memory monitor",
            level="critical",
        )
        self.stop()

    def _monitor_memory(self):
        """Memory monitoring loop"""
        process = psutil.Process()
        while not self.stop_flag.is_set():
            try:

                if os.getpid() != self._pid:
                    self.logger.log(
                        "Memory monitor detected PID mismatch, stopping",
                        level="warning",
                    )
                    break

                try:
                    process = psutil.Process(self._pid)
                except psutil.NoSuchProcess:
                    self.logger.log(
                        "Memory monitor detected missing process, stopping",
                        level="warning",
                    )
                    break

                if not process.is_running():
                    self.logger.log(
                        "Memory monitor detected process stopped, stopping",
                        level="warning",
                    )
                    break

                try:
                    # Get memory info
                    memory_info = process.memory_info()
                    system_memory = psutil.virtual_memory()
                except Exception as e:
                    self.logger.log(
                        f"Error getting memory info: {str(e)}",
                        level="error",
                        error_type=type(e).__name__,
                    )
                    break

                # Calculate usage percentages
                process_percent = (memory_info.rss / system_memory.total) * 100
                system_percent = system_memory.percent

                # Log memory stats
                self.logger.log_memory_stats(
                    process_memory_mb=memory_info.rss / (1024 * 1024),
                    process_percent=process_percent,
                    system_percent=system_percent,
                )

                # Check for high memory usage
                if system_percent > self.threshold_percent:
                    self.logger.log_memory_warning(
                        f"High system memory usage: {system_percent:.1f}%",
                        system_percent=system_percent,
                    )

                if process_percent > (
                    self.threshold_percent / 2
                ):  # Process threshold at half of system
                    self.logger.log_memory_warning(
                        f"High process memory usage: {process_percent:.1f}%",
                        process_percent=process_percent,
                    )

            except Exception as e:
                self.logger.log(
                    f"Error monitoring memory: {str(e)}",
                    level="error",
                    error_type=type(e).__name__,
                )

            time.sleep(self.check_interval)
