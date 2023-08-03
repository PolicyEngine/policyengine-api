"""Shared fixtures"""
import time
from contextlib import contextmanager
from subprocess import Popen, TimeoutExpired
import os
import redis
import pytest
from policyengine_api.api import app


@contextmanager
def running(process_arguments, seconds_to_wait_after_launch=0):
    """run a process and kill it after"""
    process = Popen(process_arguments, shell=True, env=os.environ)
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
    with running(["redis-server"], 3):
        redis_client = redis.Redis()
        redis_client.ping()
        with running(["python", "policyengine_api/worker.py"], 3):
            with app.test_client() as test_client:
                yield test_client
