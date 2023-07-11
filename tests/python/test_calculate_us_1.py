"""
# Test: run a few calls to /calculate, running them with --durations=0 should
# show that chaching is working (the ones suffixed by _repeat should be hits
# and run much faster than their equivalent without the _repeat suffix).
"""
import pytest
from policyengine_api.api import app


@pytest.fixture(name="rest_client")
def client():
    """run the app for the tests to run against"""
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def test_calculate_us_1(rest_client):
    """This should be a cache miss as no other requests have been made yet."""
    response = rest_client.post(
        "/us/calculate",
        headers={"Content-Type": "application/json"},
        data=open(
            "./tests/python/data/calculate_us_1_data.json",
            "r",
            encoding="utf-8",
        ),
    )
    assert response.status_code == 200, response.text


def test_calculate_us_2(rest_client):
    """This should be a miss as the data is different to test_calculate_us_1"""
    response = rest_client.post(
        "/us/calculate",
        headers={"Content-Type": "application/json"},
        data=open(
            "./tests/python/data/calculate_us_2_data.json",
            "r",
            encoding="utf-8",
        ),
    )
    assert response.status_code == 200, response.text


def test_calculate_us_1_repeat_1(rest_client):
    """This should be a hit as the data is the same as test_calculate_us_1"""
    response = rest_client.post(
        "/us/calculate",
        headers={"Content-Type": "application/json"},
        data=open(
            "./tests/python/data/calculate_us_1_data.json",
            "r",
            encoding="utf-8",
        ),
    )
    assert response.status_code == 200, response.text


def test_calculate_us_2_repeat_1(rest_client):
    """This should be a cache hit as the data is the same as
    test_calculate_us_2
    """
    response = rest_client.post(
        "/us/calculate",
        headers={"Content-Type": "application/json"},
        data=open(
            "./tests/python/data/calculate_us_2_data.json",
            "r",
            encoding="utf-8",
        ),
    )
    assert response.status_code == 200, response.text
