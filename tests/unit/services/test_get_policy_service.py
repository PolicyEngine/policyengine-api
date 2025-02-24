import pytest
import json

from policyengine_api.services.policy_service import PolicyService

from tests.fixtures.policy_fixtures import (
    valid_json_value,
    valid_hash_value,
    valid_policy_data,
    existing_policy_record,
)

service = PolicyService()


class TestGetPolicy:

    def test_get_policy_given_existing_record(
        self, test_db, existing_policy_record
    ):
        # GIVEN an existing record... (included as fixture)

        # WHEN we call get_policy for this record...
        result = service.get_policy(
            valid_policy_data["country_id"], valid_policy_data["id"]
        )

        expected_result = {
            "id": valid_policy_data["id"],
            "country_id": valid_policy_data["country_id"],
            "label": valid_policy_data["label"],
            "api_version": valid_policy_data["api_version"],
            "policy_json": json.loads(valid_policy_data["policy_json"]),
            "policy_hash": valid_policy_data["policy_hash"],
        }

        # THEN the result should contain the expected policy data
        assert result == expected_result

    def test_get_policy_given_nonexistent_record(self, test_db):
        # GIVEN an empty database (this is created by default)

        # WHEN we call get_policy for a nonexistent record
        NO_SUCH_RECORD_ID = 999
        result = service.get_policy("us", NO_SUCH_RECORD_ID)

        # THEN the result should be None
        assert result is None

    def test_get_policy_given_str_id(self):

        # GIVEN an invalid ID
        INVALID_RECORD_ID = "invalid"

        with pytest.raises(
            Exception,
            match=f"Invalid policy ID: {INVALID_RECORD_ID}. Must be a positive integer.",
        ):
            # WHEN we call get_policy with the invalid ID
            # THEN an exception should be raised
            service.get_policy("us", INVALID_RECORD_ID)

    def test_get_policy_given_negative_int_id(self):
        # GIVEN an invalid ID
        INVALID_RECORD_ID = -1

        with pytest.raises(
            Exception,
            match=f"Invalid policy ID: {INVALID_RECORD_ID}. Must be a positive integer.",
        ):
            # WHEN we call get_policy with the invalid ID
            # THEN an exception should be raised
            service.get_policy("us", INVALID_RECORD_ID)
