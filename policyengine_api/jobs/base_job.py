from abc import ABC, abstractmethod
import datetime
from enum import Enum

class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class BaseJob(ABC):
    def __init__(self):
        self.started_at = None
        self.completed_at = None
        self.status = JobStatus.PENDING
        self.result = None
        self.error = None
    
    # Individual jobs should implement this method
    @abstractmethod
    def run(self, *args, **kwargs):
        pass
    
    def execute(self, *args, **kwargs):
        try:
            self.start_time = datetime.datetime.now(datetime.timezone.utc)
            self.status = JobStatus.RUNNING
            self.result = self.run(*args, **kwargs)
            self.status = JobStatus.COMPLETED
        except Exception as e:
            self.status = JobStatus.FAILED
            self.error = str(e)
            raise
        finally:
            self.end_time = datetime.datetime.now(datetime.timezone.utc)