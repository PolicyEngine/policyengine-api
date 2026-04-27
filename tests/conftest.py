from pathlib import Path
import time
from contextlib import contextmanager
from subprocess import Popen, TimeoutExpired
import sys
import pytest

# Add the project root directory to PYTHONPATH
root_dir = Path(__file__).parent
sys.path.append(str(root_dir))
"""Shared fixtures"""


@contextmanager
def running(process_arguments, seconds_to_wait_after_launch=0):
    """run a process and kill it after"""
    process = Popen(process_arguments)
    time.sleep(seconds_to_wait_after_launch)
    try:
        yield process
    finally:
        process.kill()
        try:
            process.wait(10)
        except TimeoutExpired:
            process.terminate()


@pytest.fixture(name="rest_client", scope="session")
def client():
    """run the app for the tests to run against"""
    from policyengine_api.api import app
    import redis

    app.config["TESTING"] = True
    with running(["redis-server"], 3):
        redis_client = redis.Redis()
        redis_client.ping()
        with app.test_client() as test_client:
            yield test_client
