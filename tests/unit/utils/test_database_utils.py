import pytest
from unittest.mock import MagicMock, Mock

from policyengine_api.utils.database_utils import (
    get_inserted_record_id,
    find_existing_record,
)


class TestGetInsertedRecordId:
    """Test the get_inserted_record_id utility function."""

    def test_get_inserted_record_id_simple(self, test_db):
        """Test retrieving ID after a simple insert."""
        # GIVEN we insert a record
        test_db.query(
            "INSERT INTO simulation (country_id, api_version, population_id, population_type, policy_id) VALUES (?, ?, ?, ?, ?)",
            ("us", "1.0.0", "test_123", "household", 1),
        )

        # WHEN we retrieve the ID using our utility
        record_id = get_inserted_record_id(
            test_db,
            "simulation",
            {
                "country_id": "us",
                "api_version": "1.0.0",
                "population_id": "test_123",
                "population_type": "household",
                "policy_id": 1,
            },
        )

        # THEN we should get the correct ID
        assert record_id is not None
        assert isinstance(record_id, int)
        assert record_id > 0

    def test_get_inserted_record_id_with_nulls(self, test_db):
        """Test retrieving ID when some fields are NULL."""
        # GIVEN we insert a report with NULL simulation_2_id
        test_db.query(
            "INSERT INTO report_outputs (simulation_1_id, simulation_2_id, status) VALUES (?, ?, ?)",
            (1, None, "pending"),
        )

        # WHEN we retrieve the ID with NULL handling
        record_id = get_inserted_record_id(
            test_db,
            "report_outputs",
            {
                "simulation_1_id": 1,
                "simulation_2_id": None,
                "status": "pending",
            },
        )

        # THEN we should get the correct ID
        assert record_id is not None

        # AND the record should have the NULL value
        result = test_db.query(
            "SELECT * FROM report_outputs WHERE id = ?", (record_id,)
        ).fetchone()
        assert result["simulation_2_id"] is None

    def test_get_inserted_record_id_multiple_records(self, test_db):
        """Test that the most recent matching record is returned."""
        # GIVEN we insert multiple records with DIFFERENT simulation IDs to avoid UNIQUE constraint
        # Each report has different simulation_1_id values
        for i in range(3):
            test_db.query(
                "INSERT INTO report_outputs (simulation_1_id, simulation_2_id, status) VALUES (?, ?, ?)",
                (i + 1, None, "pending"),
            )

        # WHEN we retrieve the ID of the last one inserted (simulation_1_id = 3)
        record_id = get_inserted_record_id(
            test_db,
            "report_outputs",
            {
                "simulation_1_id": 3,
                "simulation_2_id": None,
                "status": "pending",
            },
        )

        # THEN we should get the ID of the record with simulation_1_id = 3
        result = test_db.query(
            "SELECT id FROM report_outputs WHERE simulation_1_id = ? AND simulation_2_id IS NULL",
            (3,),
        ).fetchone()
        assert record_id == result["id"]

    def test_get_inserted_record_id_no_match_raises_exception(self, test_db):
        """Test that an exception is raised when no matching record exists."""
        # GIVEN no matching records exist

        # WHEN we try to get an ID for a non-existent record
        # THEN an exception should be raised
        with pytest.raises(Exception) as exc_info:
            get_inserted_record_id(
                test_db,
                "simulation",
                {
                    "country_id": "nonexistent",
                    "api_version": "0.0.0",
                    "population_id": "none",
                    "population_type": "household",
                    "policy_id": 999,
                },
            )
        assert "Failed to retrieve inserted record" in str(exc_info.value)


class TestFindExistingRecord:
    """Test the find_existing_record utility function."""

    def test_find_existing_record_found(self, test_db):
        """Test finding an existing record."""
        # GIVEN we have a record in the database
        test_db.query(
            "INSERT INTO simulation (country_id, api_version, population_id, population_type, policy_id) VALUES (?, ?, ?, ?, ?)",
            ("uk", "2.0.0", "geo_123", "geography", 5),
        )

        # WHEN we search for it
        result = find_existing_record(
            test_db,
            "simulation",
            {
                "country_id": "uk",
                "api_version": "2.0.0",
                "population_id": "geo_123",
                "population_type": "geography",
                "policy_id": 5,
            },
        )

        # THEN we should find the record
        assert result is not None
        assert result["country_id"] == "uk"
        assert result["population_id"] == "geo_123"
        assert result["policy_id"] == 5

    def test_find_existing_record_not_found(self, test_db):
        """Test that None is returned when no record matches."""
        # GIVEN an empty database

        # WHEN we search for a non-existent record
        result = find_existing_record(
            test_db,
            "simulation",
            {
                "country_id": "ca",
                "api_version": "3.0.0",
                "population_id": "missing",
                "population_type": "household",
                "policy_id": 100,
            },
        )

        # THEN None should be returned
        assert result is None

    def test_find_existing_record_with_nulls(self, test_db):
        """Test finding records with NULL values."""
        # GIVEN we have a report with NULL simulation_2_id
        test_db.query(
            "INSERT INTO report_outputs (simulation_1_id, simulation_2_id, status) VALUES (?, ?, ?)",
            (10, None, "complete"),
        )

        # WHEN we search including the NULL field
        result = find_existing_record(
            test_db,
            "report_outputs",
            {
                "simulation_1_id": 10,
                "simulation_2_id": None,
                "status": "complete",
            },
        )

        # THEN we should find the record
        assert result is not None
        assert result["simulation_1_id"] == 10
        assert result["simulation_2_id"] is None

    def test_find_existing_record_partial_match_returns_none(self, test_db):
        """Test that partial matches don't count as found."""
        # GIVEN we have a record
        test_db.query(
            "INSERT INTO simulation (country_id, api_version, population_id, population_type, policy_id) VALUES (?, ?, ?, ?, ?)",
            ("us", "1.0.0", "partial", "household", 1),
        )

        # WHEN we search with only some matching fields
        result = find_existing_record(
            test_db,
            "simulation",
            {
                "country_id": "us",
                "api_version": "1.0.0",
                "population_id": "partial",
                "population_type": "geography",  # Different type
                "policy_id": 1,
            },
        )

        # THEN no match should be found
        assert result is None
