import pytest
import json
from unittest.mock import MagicMock
import re

from policyengine_api.services.household_service import HouseholdService
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS

from tests.fixtures.services.household_fixtures import (
    valid_request_body,
    valid_db_row,
    valid_hash_value,
    existing_household_record,
    mock_hash_object,
)

service = HouseholdService()


class TestGetHousehold:

    def test_get_household_given_existing_record(
        self, test_db, existing_household_record
    ):

        # GIVEN an existing record... (included as fixture)

        # WHEN we call get_household for this record...
        result = service.get_household(
            valid_db_row["country_id"], valid_db_row["id"]
        )

        valid_household_json = valid_request_body["data"]

        # THEN the result should be the expected household data
        assert result["household_json"] == valid_household_json

    def test_get_household_given_nonexistent_record(self, test_db):

        # GIVEN an empty database (this is created by default)...

        # WHEN we call get_household for a nonexistent record...
        NO_SUCH_RECORD_ID = 999

        result = service.get_household("us", NO_SUCH_RECORD_ID)

        # THEN the result should be None
        assert result is None

    def test_get_household_given_str_id(self, test_db):

        # GIVEN an invalid ID...

        INVALID_RECORD_ID = "invalid"

        with pytest.raises(
            Exception,
            match=f"Invalid household ID: {INVALID_RECORD_ID}. Must be a positive integer.",
        ):
            # WHEN we call get_household with the invalid ID...
            # THEN an exception should be raised
            service.get_household("us", INVALID_RECORD_ID)

    def test_get_household_given_negative_int_id(self, test_db):

        # GIVEN an invalid ID...
        INVALID_RECORD_ID = -1

        with pytest.raises(
            Exception,
            match=f"Invalid household ID: {INVALID_RECORD_ID}. Must be a positive integer.",
        ):
            # WHEN we call get_household with the invalid ID...
            # THEN an exception should be raised
            service.get_household("us", INVALID_RECORD_ID)


class TestCreateHousehold:
    service = HouseholdService()

    def test_create_household_given_valid_data(self, test_db):

        def fetch_created_record():
            row = test_db.query(
                "SELECT * FROM household",
            ).fetchone()
            return row

        # GIVEN valid household data and an empty database...
        # WHEN we call create_household with this data...
        country_id = "us"
        valid_json = valid_request_body["data"]
        valid_label = valid_request_body["label"]

        test_id = service.create_household(country_id, valid_json, valid_label)

        # THEN there should only be one record, and if we re-fetch it,
        # it should match the data we provided
        test_row = fetch_created_record()

        valid_json_in_db = json.dumps(valid_request_body["data"])
        valid_label_in_db = valid_request_body["label"]

        assert test_id == test_row["id"]
        assert test_row["household_json"] == valid_json_in_db
        assert test_row["label"] == valid_label_in_db

    def test_create_household_given_missing_data(self, test_db):

        # GIVEN an empty database...

        # WHEN we call create_household with missing required data...
        country_id = "us"
        valid_label = valid_request_body["label"]

        with pytest.raises(
            Exception,
            match=re.escape(
                "HouseholdService.create_household() missing 1 required positional argument: 'household_json'"
            ),
        ):
            # THEN an exception should be raised
            service.create_household(country_id, label=valid_label)


class TestUpdateHousehold:
    def test_update_household_given_existing_record(
        self, test_db, mock_hash_object, existing_household_record
    ):

        def fetch_updated_record():
            row = test_db.query(
                "SELECT * FROM household WHERE id = ?", (valid_db_row["id"],)
            ).fetchone()
            return row

        # GIVEN an existing record...(included as fixture)

        # WHEN we call update_household for this record's label and fill other necessary info...
        test_update_label = "Updated Household"

        existing_country_id = valid_db_row["country_id"]
        existing_record_id = valid_db_row["id"]
        existing_data = valid_db_row["household_json"]

        service.update_household(
            existing_country_id,
            existing_record_id,
            existing_data,
            test_update_label,
        )

        # THEN the database should be updated with the new data
        test_row = fetch_updated_record()
        assert test_row["label"] == test_update_label

    def test_update_household_given_nonexistent_record(self, test_db):

        # GIVEN an empty database...

        # WHEN we call update_household for a nonexistent record...
        NO_SUCH_RECORD_ID = 999

        existing_country_id = valid_db_row["country_id"]
        existing_data = valid_db_row["household_json"]
        existing_label = valid_db_row["label"]

        result = service.update_household(
            existing_country_id,
            NO_SUCH_RECORD_ID,
            existing_data,
            existing_label,
        )

        # THEN no record will be modified
        assert result is None
