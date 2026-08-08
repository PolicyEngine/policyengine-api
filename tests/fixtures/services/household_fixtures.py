import pytest
import json
from unittest.mock import patch

from policyengine_api.data.v1_models import Household

valid_request_body = {
    "data": {"people": {"person1": {"age": 30, "income": 50000}}},
    "label": "Test Household",
}

valid_db_row = {
    "id": 10,
    "country_id": "us",
    "household_json": json.dumps(valid_request_body["data"]),
    "household_hash": "some-hash",
    "label": "Test Household",
    "api_version": "3.0.0",
}

valid_hash_value = "some-hash"


@pytest.fixture
def mock_hash_object():
    """Mock the hash_object function."""
    with patch("policyengine_api.services.household_service.hash_object") as mock:
        mock.return_value = valid_hash_value
        yield mock


@pytest.fixture
def existing_household_record(orm_session):
    """Insert an existing household record into the database."""
    household = Household(
        id=valid_db_row["id"],
        country_id=valid_db_row["country_id"],
        household_json=json.loads(valid_db_row["household_json"]),
        household_hash=valid_db_row["household_hash"],
        label=valid_db_row["label"],
        api_version=valid_db_row["api_version"],
    )
    orm_session.add(household)
    orm_session.flush()
    return household
