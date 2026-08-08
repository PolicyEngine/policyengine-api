import json
import pytest
from unittest.mock import patch

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


@pytest.fixture
def mock_database():
    """Replace the route's service with its typed persistence boundary."""
    with patch(
        "policyengine_api.routes.household_routes.household_service"
    ) as household_service:
        yield household_service
