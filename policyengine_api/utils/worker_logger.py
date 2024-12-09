from policyengine_api.utils.logger import Logger
from rq import Worker, get_current_job
from datetime import datetime


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
