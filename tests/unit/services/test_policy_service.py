import pytest
import json
from unittest.mock import MagicMock
from policyengine_api.services.policy_service import PolicyService

from tests.fixtures.services.policy_service import valid_hash_value, valid_policy_data


pytest_plugins = ["tests.fixtures.services.policy_service"]

service = PolicyService()


class TestGetPolicy:
    def test_get_policy_given_existing_record(self, test_db, existing_policy_record):
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
        result = service.get_policy(valid_policy_data["country_id"], NO_SUCH_RECORD_ID)

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
            service.get_policy(valid_policy_data["country_id"], INVALID_RECORD_ID)

    def test_get_policy_given_negative_int_id(self):
        # GIVEN an invalid ID
        INVALID_RECORD_ID = -1

        with pytest.raises(
            Exception,
            match=f"Invalid policy ID: {INVALID_RECORD_ID}. Must be a positive integer.",
        ):
            # WHEN we call get_policy with the invalid ID
            # THEN an exception should be raised
            service.get_policy(valid_policy_data["country_id"], INVALID_RECORD_ID)

    def test_get_policy_given_invalid_country_id(self):
        # GIVEN an invalid country_id
        INVALID_COUNTRY_ID = "xx"  # Unsupported country code

        # WHEN we call get_policy with the invalid country_id
        result = service.get_policy(INVALID_COUNTRY_ID, valid_policy_data["id"])

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
    def test_set_policy_new(self, mock_hash_object):
        policies = MagicMock()
        policies.find_unique.return_value = None
        policies.create.return_value = 12
        isolated_service = PolicyService(policies)
        test_policy = {"param": "value"}
        test_label = "new_policy"
        test_country_id = "us"
        from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS

        policy_id, message, exists = isolated_service.set_policy(
            test_country_id, test_label, test_policy
        )
        assert policy_id == 12
        assert message == "Policy created"
        assert exists is False
        policies.find_unique.assert_called_once_with(
            test_country_id, valid_hash_value, test_label
        )
        policies.create.assert_called_once_with(
            test_country_id,
            test_label,
            test_policy,
            valid_hash_value,
            COUNTRY_PACKAGE_VERSIONS[test_country_id],
        )

    def test_set_policy_existing(self, mock_hash_object):
        policies = MagicMock()
        policies.find_unique.return_value = {"id": 11}
        isolated_service = PolicyService(policies)
        policy_id, message, exists = isolated_service.set_policy("us", None, {})
        assert policy_id == 11
        assert message == "Policy already exists"
        assert exists is True
        policies.create.assert_not_called()

    def test_set_policy_given_database_insert_failure(self, mock_hash_object):
        policies = MagicMock()
        policies.find_unique.return_value = None
        policies.create.side_effect = Exception("Database insertion failed")
        with pytest.raises(Exception, match="Database insertion failed"):
            PolicyService(policies).set_policy("us", "test_policy", {})

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

    def test_set_policy_given_empty_label(self, mock_hash_object):
        policies = MagicMock()
        policies.find_unique.return_value = None
        policies.create.return_value = 13
        policy_id, message, exists = PolicyService(policies).set_policy("us", "", {})
        assert policy_id == 13
        assert message == "Policy created"
        assert exists is False
        policies.find_unique.assert_called_once_with("us", valid_hash_value, None)
