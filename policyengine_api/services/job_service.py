from redis import Redis
from rq import Queue
from rq.job import Job
from policyengine_api.utils import Singleton
from policyengine_api.jobs import CalculateEconomySimulationJob
from datetime import datetime
from enum import Enum

calc_ec_sim_job = CalculateEconomySimulationJob()

queue = Queue(connection=Redis())


class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobService(metaclass=Singleton):
    """
    Hybrid service used to manage backend economy-wide simulation
    jobs. This is not connected to any routes or tables, but interfaces
    with the Redis queue to enqueue jobs and track their status.
    """
    def __init__(self):
        self.recent_jobs = {}

    def execute_job(self, job_id, job_timeout, type, *args, **kwargs):
        try:
            # Prevent duplicate jobs
            try:
                existing_job = Job.fetch(job_id, connection=queue.connection)
                if existing_job and existing_job.get_status() not in [
                    "finished",
                    "failed",
                ]:
                    print(
                        f"Job {job_id} already exists and is {existing_job.get_status()}"
                    )
                    return
            except Exception as e:
                # Job doesn't exist, continue with creation
                pass

            match type:
                case "calculate_economy_simulation":
                    queue.enqueue(
                        f=calc_ec_sim_job.run,
                        *args,
                        **kwargs,
                        job_id=job_id,
                        job_timeout=job_timeout,
                    )
                case _:
                    raise ValueError(f"Invalid job type: {type}")

            self._prune_recent_jobs()
        except Exception as e:
            print(f"Error executing job: {str(e)}")
            raise e

    def fetch_job_queue_pos(self, job_id):
        try:
            job = Job.fetch(job_id, connection=queue.connection)
            pos = (
                job.get_position()
                if type(job.get_position()) == (int or float)
                else 0
            )
            return pos
        except Exception as e:
            print(f"Error fetching job queue position: {str(e)}")
            raise e

    def get_recent_jobs(self):
        return self.recent_jobs

    def update_recent_job(self, job_id, key, value):
        self.recent_jobs[job_id][key] = value

    def add_recent_job(self, type, job_id, start_time, end_time):
        self.recent_jobs[job_id] = dict(
            type=type, start_time=start_time, end_time=end_time
        )

    def _prune_recent_jobs(self):
        if len(self.recent_jobs) > 100:
            oldest_job_id = min(
                self.recent_jobs,
                key=lambda k: self.recent_jobs[k]["start_time"],
            )
            del self.recent_jobs[oldest_job_id]

    def get_average_time(self):
        """Get the average time for the last 10 jobs. Jobs might not have an end time (None)."""
        recent_jobs = [
            job for job in self.recent_jobs.values() if job["end_time"]
        ]
        # Get 10 most recently finishing jobs
        recent_jobs = sorted(
            recent_jobs, key=lambda x: x["end_time"], reverse=True
        )[:10]
        print(recent_jobs, self.recent_jobs)
        if not recent_jobs:
            return 100
        total_time = sum(
            [
                (job["end_time"] - job["start_time"]).total_seconds()
                for job in recent_jobs
            ]
        )
        return total_time / len(recent_jobs)
