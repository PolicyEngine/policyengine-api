import sys
from pathlib import Path
import time
from contextlib import contextmanager
from subprocess import Popen, TimeoutExpired
import os
import redis
import pytest
from policyengine_api.api import app

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
    app.config["TESTING"] = True
    previous_api_key = os.environ.get("POLICYENGINE_API_AI_ANALYSIS_API_KEY")
    os.environ["POLICYENGINE_API_AI_ANALYSIS_API_KEY"] = "test-ai-analysis-key"
    with running(["redis-server"], 3):
        redis_client = redis.Redis()
        redis_client.ping()
        with running([sys.executable, "policyengine_api/worker.py"], 3):
            with app.test_client() as test_client:
                test_client.environ_base["HTTP_X_POLICYENGINE_API_KEY"] = (
                    "test-ai-analysis-key"
                )
                yield test_client
    if previous_api_key is None:
        os.environ.pop("POLICYENGINE_API_AI_ANALYSIS_API_KEY", None)
    else:
        os.environ["POLICYENGINE_API_AI_ANALYSIS_API_KEY"] = previous_api_key
