import pytest
import json
from unittest.mock import MagicMock
from sqlalchemy.engine.row import LegacyRow

from policyengine_api.services.household_service import HouseholdService
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS

from tests.fixtures.household_fixtures import (
    valid_household_json_dict,
    valid_db_row,
    valid_hash_value,
    mock_hash_object,
)

service = HouseholdService()


class TestGetHousehold:

    def test_get_household_given_existing_record(self, test_db):

        def given_existing_household_record():
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

        # GIVEN an existing record...
        given_existing_household_record()

        # WHEN we call get_household for this record...
        result = service.get_household(
            valid_db_row["country_id"], valid_db_row["id"]
        )

        # THEN the result should be the expected household data
        assert result["household_json"] == valid_household_json_dict["data"]

    def test_get_household_given_nonexistent_record(self, test_db):

        NO_SUCH_RECORD_ID = 999

        # GIVEN an empty database...
        print(test_db.query("SELECT * FROM household").fetchall())

        # WHEN we call get_household for a nonexistent record...
        result = service.get_household("us", NO_SUCH_RECORD_ID)

        # THEN the result should be None
        assert result is None

    def test_get_household_given_str_id(self, test_db):

        INVALID_RECORD_ID = "invalid"

        # GIVEN an invalid ID...
        with pytest.raises(
            Exception,
            match=f"Invalid household ID: {INVALID_RECORD_ID}. Must be a positive integer.",
        ):
            print(Exception)
            # WHEN we call get_household with the invalid ID...
            # THEN an exception should be raised
            service.get_household("us", INVALID_RECORD_ID)

    def test_get_household_given_negative_int_id(self, test_db):

        INVALID_RECORD_ID = -1

        # GIVEN an invalid ID...
        with pytest.raises(
            Exception,
            match=f"Invalid household ID: {INVALID_RECORD_ID}. Must be a positive integer.",
        ):
            print(Exception)
            # WHEN we call get_household with the invalid ID...
            # THEN an exception should be raised
            service.get_household("us", INVALID_RECORD_ID)


class TestCreateHousehold:
    service = HouseholdService()

    def test_create_household_given_valid_data(self, test_db):

        # GIVEN valid household data...
        # WHEN we call create_household with this data...
        household_id = service.create_household(
            "us",
            valid_household_json_dict["data"],
            valid_household_json_dict["label"],
        )

        # THEN the ID of the created household should be returned
        assert household_id == valid_db_row["id"]


class TestUpdateHousehold:
    def test_update_household_given_existing_record(
        self, test_db, mock_hash_object
    ):

        test_update_label = "Updated Household"

        def given_existing_household_record():
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

        def fetch_updated_record():
            row = test_db.query(
                "SELECT * FROM household WHERE id = ?", (valid_db_row["id"],)
            ).fetchone()
            return row

        # GIVEN an existing record...
        given_existing_household_record()

        # WHEN we call update_household for this record's label and fill other necessary info...
        service.update_household(
            valid_db_row["country_id"],
            valid_db_row["id"],
            valid_household_json_dict["data"],
            test_update_label,
        )

        # THEN the database should be updated with the new data
        test_row = fetch_updated_record()
        assert test_row["label"] == test_update_label

    def test_update_household_given_nonexistent_record(self, test_db):

        NO_SUCH_RECORD_ID = 999

        # GIVEN an empty database...

        # WHEN we call update_household for a nonexistent record...
        result = service.update_household(
            "us",
            NO_SUCH_RECORD_ID,
            valid_household_json_dict["data"],
            valid_household_json_dict["label"],
        )

        # THEN no record will be modified
        assert result is None
