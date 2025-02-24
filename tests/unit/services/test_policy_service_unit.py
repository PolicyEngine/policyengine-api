import pytest
import json
from unittest.mock import MagicMock


from policyengine_api.services.policy_service import PolicyService

from tests.fixtures.policy_fixtures import (
    valid_policy_format,
    #valid_hash_value,
    #mock_hash_object,
    existing_policy_record,
)

service = PolicyService()

class TestGetPolicyJson: 
    def test_get_policy_json_given_existing_record(self, test_db, existing_policy_record):

        # GIVEN an existing record... (included as fixture)

        # WHEN we call get_policy_json for this record...
        result = service.get_policy_json(
            valid_policy_format["country_id"], valid_policy_format["id"]
        )

        valid_policy_json = valid_policy_format["policy_json"]

        #THEN result should be the expected policy json
        assert result == valid_policy_json
    
    def test_get_policy_json_given_nonexisting_record(self, test_db):

        # GIVEN an empty database... (created by default)

        # WHEN we call get_policy_json for nonexistent record...
        NO_SUCH_RECORD_ID = 999
        result = service.get_policy_json('us', NO_SUCH_RECORD_ID)

        #THEN result should be the expected policy json
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
            service.get_policy_json('us', INVALID_RECORD_ID)

    def test_get_policy_json_given_negative_int_id(self, test_db):

        # GIVEN an invalid ID...

        INVALID_RECORD_ID = -1

        with pytest.raises(
            Exception,
            match=f"Invalid policy ID: {INVALID_RECORD_ID}. Must be a positive integer.",
        ):
            # WHEN we call get_policy_json with the invalid ID...
            # THEN an exception should be raised
            service.get_policy_json('us', INVALID_RECORD_ID)