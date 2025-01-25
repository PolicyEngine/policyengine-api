import pytest
import json
from unittest.mock import MagicMock
from sqlalchemy.engine.row import LegacyRow

from policyengine_api.services.household_service import HouseholdService
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS

from tests.fixtures.household_fixtures import (
    test_household_data,
    test_db_row,
    test_hash_value,
    mock_database,
    mock_hash_object,
)

service = HouseholdService()


class TestGetHousehold:

    def test_get_household_given_existing_record(self, mock_database):

        # GIVEN an existing record...
        mock_row = MagicMock(spec=LegacyRow)
        mock_row.__getitem__.side_effect = lambda x: test_db_row[x]
        mock_row.keys.return_value = test_db_row.keys()
        mock_database.query().fetchone.return_value = mock_row

        # WHEN we call get_household for this record...
        result = service.get_household("us", 10)

        # THEN the result should be the expected household data
        assert result["household_json"] == test_household_data["data"]

    def test_get_household_given_nonexistent_record(self, mock_database):

        # GIVEN an empty database...
        mock_database.query().fetchone.return_value = None

        # WHEN we call get_household for a nonexistent record...
        result = service.get_household("us", 999)

        # THEN the result should be None
        assert result is None

    def test_get_household_given_invalid_id(self, mock_database):

        # GIVEN an invalid ID...
        with pytest.raises(Exception):
            # WHEN we call get_household with the invalid ID...
            # THEN an exception should be raised
            service.get_household("us", "invalid")


class TestCreateHousehold:
    service = HouseholdService()

    def test_create_household_given_valid_data(self, mock_database):

        # Mock database response for the ID query
        mock_row = MagicMock(spec=LegacyRow)
        mock_row.__getitem__.side_effect = lambda x: {"id": test_db_row["id"]}[
            x
        ]
        mock_database.query().fetchone.return_value = mock_row

        # GIVEN valid household data...
        # WHEN we call create_household with this data...
        household_id = service.create_household(
            "us", test_household_data["data"], test_household_data["label"]
        )

        # THEN the ID of the created household should be returned
        assert household_id == test_db_row["id"]
        mock_database.query.assert_called()


class TestUpdateHousehold:
    def test_update_household_given_existing_record(
        self, mock_database, mock_hash_object
    ):

        test_update_label = "Updated Household"

        # GIVEN an existing record...
        mock_row = MagicMock(spec=LegacyRow)
        mock_row.__getitem__.side_effect = lambda x: test_db_row[x]
        mock_row.keys.return_value = test_db_row.keys()
        mock_database.query().fetchone.return_value = mock_row

        # WHEN we call update_household for this record...
        service.update_household(
            test_db_row["country_id"],
            test_db_row["id"],
            test_household_data["data"],
            test_update_label,
        )

        # THEN the database should be updated with the new data
        mock_database.query.assert_any_call(
            "UPDATE household SET household_json = ?, household_hash = ?, label = ?, api_version = ? WHERE id = ?",
            (
                json.dumps(test_household_data["data"]),
                test_hash_value,
                test_update_label,
                COUNTRY_PACKAGE_VERSIONS.get(test_db_row["country_id"]),
                test_db_row["id"],
            ),
        )

    def test_update_household_given_nonexistent_record(self, mock_database):

        # GIVEN an empty database...
        mock_database.query().fetchone.return_value = None

        # WHEN we call update_household for a nonexistent record...
        result = service.update_household(
            "us",
            999,
            test_household_data["data"],
            test_household_data["label"],
        )

        # THEN no record will be modified
        assert result is None
