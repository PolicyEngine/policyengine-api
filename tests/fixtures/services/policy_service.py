import pytest
import json
from unittest.mock import patch

from policyengine_api.data.v1_models import Policy

valid_policy_json = {
    "data": {"gov.irs.income.bracket.rates.2": {"2024-01-01.2024-12-31": 0.2433}},
}

valid_hash_value = "NgJhpeuRVnIAwgYWuJsd2fI/N88rIE6Kcj8q4TPD/i4="

# Sample valid policy data
valid_policy_data = {
    "id": 11,
    "country_id": "us",
    "label": None,
    "api_version": "1.180.1",
    "policy_json": json.dumps(valid_policy_json["data"]),
    "policy_hash": valid_hash_value,
}


@pytest.fixture
def mock_hash_object():
    """Mock the hash_object function."""
    with patch("policyengine_api.services.policy_service.hash_object") as mock:
        mock.return_value = valid_hash_value
        yield mock


@pytest.fixture
def existing_policy_record(orm_session):
    """Insert an existing policy record into the database."""
    policy = Policy(
        id=valid_policy_data["id"],
        country_id=valid_policy_data["country_id"],
        policy_json=json.loads(valid_policy_data["policy_json"]),
        policy_hash=valid_policy_data["policy_hash"],
        label=valid_policy_data["label"],
        api_version=valid_policy_data["api_version"],
    )
    orm_session.add(policy)
    orm_session.flush()
    return policy
