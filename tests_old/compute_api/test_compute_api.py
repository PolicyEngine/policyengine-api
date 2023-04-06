import yaml
import json
import pytest
from pathlib import Path
from policyengine_api.compute_api import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


# Each YAML file in the tests directory is a test case.
# The test case is a dictionary with the following keys:

# - name: the name of the test case
# - endpoint: the endpoint to test
# - method: the HTTP method to use
# - data: the data to send to the endpoint if the method is POST
# - expected_status: the expected HTTP status code
# - expected_result: the expected result of the endpoint

test_paths = [
    path
    for path in (Path(__file__).parent).iterdir()
    if path.suffix == ".yaml"
]
test_data = [yaml.safe_load(path.read_text()) for path in test_paths]
test_names = [test["name"] for test in test_data]


def assert_response_data_matches_expected(data: dict, expected: dict):
    # For every key in expected, check that the corresponding key in data
    # has the same value.
    for key, value in expected.items():
        if key not in data:
            raise ValueError(f"Key {key} not found in response data.")
        if isinstance(value, dict):
            assert_response_data_matches_expected(data[key], value)
        elif data[key] != value:
            raise ValueError(
                f"Value {data[key]} for key {key} does not match expected value {value}."
            )


@pytest.mark.parametrize("test", test_data, ids=test_names)
def test_response(client, test: dict):
    if test.get("method", "GET") == "GET":
        response = client.get(test["endpoint"])
    elif test.get("method") == "POST":
        response = client.post(
            test["endpoint"],
            data=json.dumps(test["data"]),
            content_type="application/json",
        )
    else:
        raise ValueError(f"Unknown HTTP method: {test['method']}")

    assert response.status_code == test.get("response", {}).get("status", 200)
    if "data" in test.get("response", {}):
        assert_response_data_matches_expected(
            json.loads(response.data), test.get("response", {}).get("data", {})
        )
    elif "html" in test.get("response", {}):
        assert response.data.decode("utf-8") == test.get("response", {}).get(
            "html", ""
        )
