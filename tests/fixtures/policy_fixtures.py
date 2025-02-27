import pytest
import json
from unittest.mock import patch


valid_policy_format = {
    "id": 11,
    "country_id": "us",
    "label": None,
    "api_version": "1.180.1",
    "policy_json": json.dumps(
        {"gov.irs.income.bracket.rates.2": {"2024-01-01.2024-12-31": 0.2433}}
    ),
    "policy_hash": "NgJhpeuRVnIAwgYWuJsd2fI/N88rIE6Kcj8q4TPD/i4=",
}

valid_hash_value = "NgJhpeuRVnIAwgYWuJsd2fI/N88rIE6Kcj8q4TPD/i4="


@pytest.fixture
def mock_hash_object():
    """Mock the has_object function."""
    with patch("policyengine_api.services.policy_service.hash_object") as mock:
        mock.return_value = valid_hash_value
        yield mock


@pytest.fixture
def existing_policy_record(test_db):
    """Insert an existig policy record into the database."""
    test_db.query(
        "INSERT INTO policy (id, country_id, label, api_version, policy_json, policy_hash) VALUES (?, ?, ?, ?, ?, ?)",
        (
            valid_policy_format["id"],
            valid_policy_format["country_id"],
            valid_policy_format["label"],
            valid_policy_format["api_version"],
            valid_policy_format["policy_json"],
            valid_policy_format["policy_hash"],
        ),
    )
    inserted_row = test_db.query(
        "SELECT * FROM policy WHERE id = ?", (valid_policy_format["id"],)
    ).fetchone()

    return inserted_row
