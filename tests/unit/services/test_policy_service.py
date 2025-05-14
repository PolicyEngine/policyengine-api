import pytest
import json
from unittest.mock import call
from policyengine_api.services.policy_service import PolicyService

from tests.fixtures.services.policy_service import (
    valid_policy_data,
    valid_hash_value,
    mock_hash_object,
    mock_database,
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
        result = service.get_policy(
            valid_policy_data["country_id"], NO_SUCH_RECORD_ID
        )

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
            service.get_policy(
                valid_policy_data["country_id"], INVALID_RECORD_ID
            )

    def test_get_policy_given_negative_int_id(self):
        # GIVEN an invalid ID
        INVALID_RECORD_ID = -1

        with pytest.raises(
            Exception,
            match=f"Invalid policy ID: {INVALID_RECORD_ID}. Must be a positive integer.",
        ):
            # WHEN we call get_policy with the invalid ID
            # THEN an exception should be raised
            service.get_policy(
                valid_policy_data["country_id"], INVALID_RECORD_ID
            )

    def test_get_policy_given_invalid_country_id(self):
        # GIVEN an invalid country_id
        INVALID_COUNTRY_ID = "xx"  # Unsupported country code

        # WHEN we call get_policy with the invalid country_id
        result = service.get_policy(
            INVALID_COUNTRY_ID, valid_policy_data["id"]
        )

        # THEN the result should be None or raise an exception
        assert result is None

    def test_get_policy_given_empty_string_country_id(self):
        # GIVEN an empty string as country_id
        EMPTY_COUNTRY_ID = ""

        # WHEN we call get_policy with country_id = ""
        with pytest.raises(
            Exception,
            match="country_id cannot be empty or None",
        ):
            # THEN an exception should be raised
            service.get_policy(EMPTY_COUNTRY_ID, valid_policy_data["id"])

    def test_get_policy_given_none_country_id(self):
        # GIVEN a country_id of None
        NONE_COUNTRY_ID = None

        # WHEN we call get_policy with country_id = None
        with pytest.raises(
            Exception,
            match="country_id cannot be empty or None",
        ):
            # THEN an exception should be raised
            service.get_policy(NONE_COUNTRY_ID, valid_policy_data["id"])


class TestGetPolicyJson:
    def test_get_policy_json_given_existing_record(
        self, test_db, existing_policy_record
    ):

        # GIVEN an existing record... (included as fixture)

        # WHEN we call get_policy_json for this record...
        result = service.get_policy_json(
            valid_policy_data["country_id"], valid_policy_data["id"]
        )

        valid_policy_json = valid_policy_data["policy_json"]

        # THEN result should be the expected policy json
        assert result == valid_policy_json

    def test_get_policy_json_given_nonexisting_record(self, test_db):

        # GIVEN an empty database... (created by default)

        # WHEN we call get_policy_json for nonexistent record...
        NO_SUCH_RECORD_ID = 999
        result = service.get_policy_json("us", NO_SUCH_RECORD_ID)

        # THEN result should be None
        assert result is None

    def test_get_policy_json_given_str_id(self, test_db):

        # GIVEN an invalid ID...

        INVALID_RECORD_ID = "invalid"

        with pytest.raises(
            Exception,
            match=f"Invalid policy ID: {INVALID_RECORD_ID}. Must be a positive integer.",
        ):
            # WHEN we call get_policy_json with the invalid ID...
            # THEN an exception should be raised
            service.get_policy_json("us", INVALID_RECORD_ID)

    def test_get_policy_json_given_negative_int_id(self, test_db):

        # GIVEN an invalid ID...

        INVALID_RECORD_ID = -1

        with pytest.raises(
            Exception,
            match=f"Invalid policy ID: {INVALID_RECORD_ID}. Must be a positive integer.",
        ):
            # WHEN we call get_policy_json with the invalid ID...
            # THEN an exception should be raised
            service.get_policy_json("us", INVALID_RECORD_ID)


class TestSetPolicy:
    def test_set_policy_new(self, mock_database, mock_hash_object):
        # GIVEN a new policy to insert
        new_policy_id = 12  # Different from existing fixture ID
        test_policy = {"param": "value"}
        test_label = "new_policy"
        test_country_id = "us"

        # Get current API version dynamically
        from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS

        current_api_version = COUNTRY_PACKAGE_VERSIONS.get(test_country_id)

        # Setup mocks
        mock_database.query.return_value.fetchone.side_effect = [
            None,  # First call: policy does not exist
            {"id": new_policy_id},  # Second call: fetch newly inserted policy
        ]

        # Define expected database calls
        expected_calls = [
            # First call - check if policy exists
            call(
                "SELECT * FROM policy WHERE country_id = ? AND policy_hash = ? AND label = ?",
                (test_country_id, valid_hash_value, test_label),
            ),
            # Second call - insert new policy
            call(
                "INSERT INTO policy (country_id, policy_json, policy_hash, label, api_version) VALUES (?, ?, ?, ?, ?)",
                (
                    test_country_id,
                    json.dumps(test_policy),
                    valid_hash_value,
                    test_label,
                    current_api_version,  # From COUNTRY_PACKAGE_VERSIONS for 'us'
                ),
            ),
            # Third call - fetch the newly created policy
            call(
                "SELECT * FROM policy WHERE country_id = ? AND policy_hash = ? AND label = ?",
                (test_country_id, valid_hash_value, test_label),
            ),
        ]

        # WHEN we call set_policy
        policy_id, message, exists = service.set_policy(
            test_country_id, test_label, test_policy
        )

        # THEN the result should indicate a new policy was created
        assert policy_id == new_policy_id
        assert message == "Policy created"
        assert exists is False

        # Verify the database queries were called as expected
        assert mock_database.query.call_args_list == expected_calls

    def test_set_policy_existing(
        self, mock_database, mock_hash_object, existing_policy_record
    ):
        # GIVEN an existing policy record
        existing_policy = existing_policy_record

        # Setup mock
        mock_database.query.return_value.fetchone.return_value = (
            existing_policy
        )

        # Define expected database calls - matches actual implementation
        expected_calls = [
            call(
                "SELECT * FROM policy WHERE country_id = ? AND policy_hash = ? AND label IS NULL",
                (
                    existing_policy["country_id"],
                    valid_hash_value,
                ),  # No None parameter for IS NULL
            ),
        ]

        # WHEN we call set_policy with existing policy data
        policy_id, message, exists = service.set_policy(
            existing_policy["country_id"],
            existing_policy["label"],
            json.loads(existing_policy["policy_json"]),
        )

        # THEN the result should indicate the policy already exists
        assert policy_id == existing_policy["id"]
        assert message == "Policy already exists"
        assert exists is True

        # Verify the database query was called as expected
        assert mock_database.query.call_args_list == expected_calls

    def test_set_policy_given_database_insert_failure(
        self, mock_database, mock_hash_object
    ):
        # GIVEN a database insertion failure
        test_policy = {"param": "value"}
        test_label = "test_policy"
        test_country_id = "us"

        # Setup mock to raise exception on insert
        mock_database.query.return_value.fetchone.side_effect = [
            None,  # First call: policy does not exist
            Exception(
                "Database insertion failed"
            ),  # Second call: insertion fails
        ]

        # WHEN we call set_policy
        with pytest.raises(Exception, match="Database insertion failed"):
            # THEN an exception should be raised
            service.set_policy(test_country_id, test_label, test_policy)

    def test_set_policy_given_invalid_country_id(self, mock_hash_object):
        # GIVEN an invalid country_id
        INVALID_COUNTRY_ID = "xx"  # Unsupported country code
        test_policy = {"param": "value"}
        test_label = "test_policy"

        # WHEN we call set_policy with an invalid country_id
        with pytest.raises(
            ValueError, match=f"Invalid country_id: {INVALID_COUNTRY_ID}"
        ):
            # THEN an exception should be raised
            service.set_policy(INVALID_COUNTRY_ID, test_label, test_policy)

    def test_set_policy_given_empty_label(
        self, mock_database, mock_hash_object
    ):
        # GIVEN an empty label
        EMPTY_LABEL = ""
        test_policy = {"param": "value"}
        test_country_id = "us"

        # Setup mock
        mock_database.query.return_value.fetchone.side_effect = [
            None,  # Policy does not exist
            {"id": 13},  # Return mock policy after creation
        ]

        # WHEN we call set_policy with an empty label
        policy_id, message, exists = service.set_policy(
            test_country_id, EMPTY_LABEL, test_policy
        )

        # THEN the result should indicate a new policy was created
        assert policy_id == 13
        assert message == "Policy created"
        assert exists is False
