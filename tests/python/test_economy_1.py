"""
Test basics for /economy endpoints.
"""
import json
import subprocess
from subprocess import Popen, TimeoutExpired
import redis
import pytest
from policyengine_api.api import app


@pytest.fixture(name="rest_client", scope="session")
def client():
    """run the app for the tests to run against"""
    app.config["TESTING"] = True
    with Popen(["redis-server"]) as redis_server:
        redis_client = redis.Redis()
        redis_client.ping()
        with Popen(
            ["python", "policyengine_api/worker.py"], stdout=subprocess.PIPE
        ) as worker:
            # output, err = worker.communicate(timeout=2)
            # pytest.logging.info(f"err={err}, output={output}")
            with app.test_client() as test_client:
                yield test_client
            worker.kill()
            try:
                worker.wait(10)
            except TimeoutExpired:
                worker.terminate()
        redis_server.kill()
        try:
            redis_server.wait(10)
        except TimeoutExpired:
            redis_server.terminate()


def test_economy_1(rest_client):
    """Add a simple policy and get /economy for that over 2."""
    policy_create = rest_client.post(
        "/us/policy",
        headers={"Content-Type": "application/json"},
        data=open(
            "./tests/python/data/test_economy_1_policy_1.json",
            "r",
            encoding="utf-8",
        ),
    )
    assert policy_create.status_code == 201
    assert policy_create.json["result"] is not None
    policy_id = policy_create.json["result"]["policy_id"]
    assert policy_id is not None
    policy_response = rest_client.get(f"/us/policy/{policy_id}")
    assert policy_response.status_code == 200
    assert policy_response.json["status"] == "ok"
    assert policy_response.json["result"]["id"] == policy_id
    policy = policy_response.json["result"]["policy_json"]
    assert policy is not None
    assert policy["gov.abolitions.ccdf_income"] is not None
    assert policy["gov.irs.income.exemption.amount"] is not None
    assert (
        policy["gov.abolitions.ccdf_income"]["2023-01-01.2028-12-31"] is True
    )
    assert (
        policy["gov.irs.income.exemption.amount"]["2023-01-01.2028-12-31"]
        == "100"
    )
    query = f"/us/economy/{policy_id}/over/2?region=us&time_period=2023"
    economy_response = rest_client.get(query)
    assert economy_response.status_code == 200
    with open(
        "./tests/python/data/test_economy_1_expected_response_1.json",
        "r",
        encoding="utf-8",
    ) as file:
        assert (
            economy_response.json["status"] == "computing"
        ), 'Expected first answer status to be "computing" but it is ' + str(
            economy_response.json["status"]
        )
        while economy_response.json["status"] == "computing":
            assert (
                economy_response.json["average_time"] is not None
            ), 'Expected computing answer to have "average_time"'
            economy_response = rest_client.get(query)
        assert economy_response.json == json.load(file)
