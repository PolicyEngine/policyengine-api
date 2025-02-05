import pytest
import json
from unittest.mock import patch


valid_household_json_dict = {
    "data": {"people": {"person1": {"age": 30, "income": 50000}}},
    "label": "Test Household",
}

valid_db_row = {
    "id": 10,
    "country_id": "us",
    "household_json": json.dumps(valid_household_json_dict["data"]),
    "household_hash": "some-hash",
    "label": "Test Household",
    "api_version": "3.0.0",
}

valid_hash_value = "some-hash"


@pytest.fixture
def mock_hash_object():
    """Mock the hash_object function."""
    with patch(
        "policyengine_api.services.household_service.hash_object"
    ) as mock:
        mock.return_value = valid_hash_value
        yield mock
