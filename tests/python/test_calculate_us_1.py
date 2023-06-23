import requests
import json
from policyengine_api.api import app
import pytest


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

# trying to check cache, _1 has exactly the same data as _2 but different order so different cache key
def test_calculate_us_1():
    response = requests.post(
        "http://localhost:5000/us/calculate",
        headers={"Content-Type": "application/json"},
        data=open("./tests/python/data/calculate_us_1_data.json", "r"),
    )
    assert response.status_code == 200
    print(response.text)

def test_calculate_us_2():
    response = requests.post(
        "http://localhost:5000/us/calculate",
        headers={"Content-Type": "application/json"},
        data=open("./tests/python/data/calculate_us_2_data.json", "r"),
    )
    assert response.status_code == 200
    print(response.text)

def test_calculate_us_1_repeat_1():
    response = requests.post(
        "http://localhost:5000/us/calculate",
        headers={"Content-Type": "application/json"},
        data=open("./tests/python/data/calculate_us_1_data.json", "r"),
    )
    assert response.status_code == 200
    print(response.text)

def test_calculate_us_2_repeat_1():
    response = requests.post(
        "http://localhost:5000/us/calculate",
        headers={"Content-Type": "application/json"},
        data=open("./tests/python/data/calculate_us_2_data.json", "r"),
    )
    assert response.status_code == 200
    print(response.text)
