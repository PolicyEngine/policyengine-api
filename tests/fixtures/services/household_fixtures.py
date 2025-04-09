import pytest
import json
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

valid_hash_value = "some-hash"


@pytest.fixture
def mock_hash_object():
    """Mock the hash_object function."""
    with patch(
        "policyengine_api.services.household_service.hash_object"
    ) as mock:
        mock.return_value = valid_hash_value
        yield mock


@pytest.fixture
def existing_household_record(test_db):
    """Insert an existing household record into the database."""
    test_db.query(
        "INSERT INTO household (id, country_id, household_json, household_hash, label, api_version) VALUES (?, ?, ?, ?, ?, ?)",
        (
            valid_db_row["id"],
            valid_db_row["country_id"],
            valid_db_row["household_json"],
            valid_db_row["household_hash"],
            valid_db_row["label"],
            valid_db_row["api_version"],
        ),
    )

    inserted_row = test_db.query(
        "SELECT * FROM household WHERE id = ?", (valid_db_row["id"],)
    ).fetchone()

    return inserted_row
