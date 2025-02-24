import pytest
import json
from unittest.mock import patch

valid_json_value = {
    "data": {"gov.irs.income.bracket.rates.2": {"2024-01-01.2024-12-31": 0.2433}},
}

valid_hash_value = "NgJhpeuRVnIAwgYWuJsd2fI/N88rIE6Kcj8q4TPD/i4="

# Sample valid policy data
valid_policy_data = {
    "id": 11,
    "country_id": "us",
    "label": None,
    "api_version": "1.180.1",
    "policy_json": json.dumps(valid_json_value["data"]),
    "policy_hash": valid_hash_value,
}


@pytest.fixture
def mock_hash_object():
    """Mock the hash_object function."""
    with patch("policyengine_api.services.policy_service.hash_object") as mock:
        mock.return_value = valid_hash_value
        yield mock


# @pytest.fixture
# def mock_database():
#     """Mock the database module."""
#     with patch("policyengine_api.services.policy_service.database") as mock_db:
#         yield mock_db


@pytest.fixture
def existing_policy_record(test_db):
    """Insert an existing policy record into the database."""
    test_db.query(
        "INSERT INTO policy (id, country_id, policy_json, policy_hash, label, api_version) VALUES (?, ?, ?, ?, ?, ?)",
        (
            valid_policy_data["id"],
            valid_policy_data["country_id"],
            valid_policy_data["policy_json"],
            valid_policy_data["policy_hash"],
            valid_policy_data["label"],
            valid_policy_data["api_version"],
        ),
    )

    inserted_row = test_db.query(
        "SELECT * FROM policy WHERE id = ?", (valid_policy_data["id"],)
    ).fetchone()

    return inserted_row
