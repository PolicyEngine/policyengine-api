import pytest
import json
from unittest.mock import patch


SAMPLE_HOUSEHOLD_DATA = {
    "data": {"people": {"person1": {"age": 30, "income": 50000}}},
    "label": "Test Household",
}

SAMPLE_DB_ROW = {
    "id": 1,
    "country_id": "us",
    "household_json": json.dumps(SAMPLE_HOUSEHOLD_DATA["data"]),
    "household_hash": "some-hash",
    "label": "Test Household",
    "api_version": "3.0.0",
}


# These will be moved to the correct location once
# testing PR that creates folder structure is merged
@pytest.fixture
def mock_database():
    """Mock the database module."""
    with patch(
        "policyengine_api.services.household_service.database"
    ) as mock_db:
        yield mock_db


@pytest.fixture
def mock_hash_object():
    """Mock the hash_object function."""
    with patch(
        "policyengine_api.services.household_service.hash_object"
    ) as mock:
        mock.return_value = "some-hash"
        yield mock
