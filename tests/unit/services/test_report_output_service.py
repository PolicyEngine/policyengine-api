import pytest
import json
from unittest.mock import MagicMock, patch
from datetime import datetime

from policyengine_api.services.report_output_service import ReportOutputService

from tests.fixtures.services.report_output_fixtures import (
    valid_report_data,
    existing_report_record,
    sample_report_output,
)

service = ReportOutputService()


class TestFindExistingReportOutput:
    """Test finding existing report outputs in the database."""

    def test_find_existing_report_output_found(self, test_db, existing_report_record):
        """Test finding an existing report output."""
        # GIVEN an existing report record (from fixture)

        # WHEN we search for a report with matching simulation IDs
        result = service.find_existing_report_output(
            simulation_1_id=existing_report_record["simulation_1_id"],
            simulation_2_id=existing_report_record["simulation_2_id"],
        )

        # THEN the result should contain the existing report
        assert result is not None
        assert result["id"] == existing_report_record["id"]
        assert result["simulation_1_id"] == existing_report_record["simulation_1_id"]
        assert result["status"] == existing_report_record["status"]

    def test_find_existing_report_output_not_found(self, test_db):
        """Test that None is returned when no report exists."""
        # GIVEN an empty database

        # WHEN we search for a non-existent report
        result = service.find_existing_report_output(
            simulation_1_id=999,
            simulation_2_id=888,
        )

        # THEN None should be returned
        assert result is None

    def test_find_existing_report_output_with_null_simulation2(self, test_db):
        """Test finding reports where simulation_2_id is NULL."""
        # GIVEN a report with NULL simulation_2_id
        test_db.query(
            "INSERT INTO report_outputs (simulation_1_id, simulation_2_id, status) VALUES (?, ?, ?)",
            (100, None, "complete"),
        )

        # WHEN we search for it
        result = service.find_existing_report_output(
            simulation_1_id=100,
            simulation_2_id=None,
        )

        # THEN we should find it
        assert result is not None
        assert result["simulation_1_id"] == 100
        assert result["simulation_2_id"] is None


class TestCreateReportOutput:
    """Test creating new report outputs in the database."""

    def test_create_report_output_single_simulation(self, test_db):
        """Test creating a report output with a single simulation."""
        # GIVEN an empty database

        # WHEN we create a report output with one simulation
        report_id = service.create_report_output(
            simulation_1_id=1,
            simulation_2_id=None,
        )

        # THEN a valid ID should be returned
        assert report_id is not None
        assert isinstance(report_id, int)
        assert report_id > 0

        # AND the report should be in the database with 'pending' status
        result = test_db.query(
            "SELECT * FROM report_outputs WHERE id = ?", (report_id,)
        ).fetchone()
        assert result is not None
        assert result["simulation_1_id"] == 1
        assert result["simulation_2_id"] is None
        assert result["status"] == "pending"

    def test_create_report_output_comparison(self, test_db):
        """Test creating a report output comparing two simulations."""
        # GIVEN an empty database

        # WHEN we create a report output with two simulations
        report_id = service.create_report_output(
            simulation_1_id=1,
            simulation_2_id=2,
        )

        # THEN a valid ID should be returned
        assert report_id is not None

        # AND the report should have both simulation IDs
        result = test_db.query(
            "SELECT * FROM report_outputs WHERE id = ?", (report_id,)
        ).fetchone()
        assert result["simulation_1_id"] == 1
        assert result["simulation_2_id"] == 2
        assert result["status"] == "pending"

    def test_create_report_output_retrieves_correct_id(self, test_db):
        """Test that create_report_output retrieves the correct ID without race conditions."""
        # GIVEN we create multiple reports rapidly

        # WHEN we create reports with different parameters
        ids = []
        for i in range(3):
            report_id = service.create_report_output(
                simulation_1_id=i + 1,
                simulation_2_id=None if i % 2 == 0 else i + 10,
            )
            ids.append(report_id)

        # THEN all IDs should be unique
        assert len(set(ids)) == 3

        # AND each report should have the correct data
        for i, report_id in enumerate(ids):
            result = test_db.query(
                "SELECT * FROM report_outputs WHERE id = ?", (report_id,)
            ).fetchone()
            assert result["simulation_1_id"] == i + 1
            expected_sim2 = None if i % 2 == 0 else i + 10
            assert result["simulation_2_id"] == expected_sim2


class TestGetReportOutput:
    """Test retrieving report outputs from the database."""

    def test_get_report_output_existing(self, test_db, existing_report_record):
        """Test retrieving an existing report output."""
        # GIVEN an existing report record

        # WHEN we retrieve the report
        result = service.get_report_output(
            report_output_id=existing_report_record["id"]
        )

        # THEN the correct report should be returned
        assert result is not None
        assert result["id"] == existing_report_record["id"]
        assert result["simulation_1_id"] == existing_report_record["simulation_1_id"]
        assert result["status"] == existing_report_record["status"]

    def test_get_report_output_nonexistent(self, test_db):
        """Test retrieving a non-existent report returns None."""
        # GIVEN an empty database

        # WHEN we try to retrieve a non-existent report
        result = service.get_report_output(report_output_id=999)

        # THEN None should be returned
        assert result is None

    def test_get_report_output_with_json_output(self, test_db):
        """Test that JSON output is properly parsed when retrieved."""
        # GIVEN a report with JSON output
        test_output = {"key": "value", "nested": {"data": 123}}
        test_db.query(
            """INSERT INTO report_outputs 
            (simulation_1_id, simulation_2_id, status, output) 
            VALUES (?, ?, ?, ?)""",
            (1, None, "complete", json.dumps(test_output)),
        )
        
        # Get the ID of the inserted record
        record = test_db.query(
            "SELECT id FROM report_outputs ORDER BY id DESC LIMIT 1"
        ).fetchone()

        # WHEN we retrieve the report
        result = service.get_report_output(report_output_id=record["id"])

        # THEN the output should be parsed from JSON
        assert result["output"] == test_output
        assert result["output"]["nested"]["data"] == 123

    def test_get_report_output_invalid_id(self, test_db):
        """Test that invalid report IDs are handled properly."""
        # GIVEN any database state

        # WHEN we call get_report_output with invalid ID types
        # THEN an exception should be raised
        with pytest.raises(Exception) as exc_info:
            service.get_report_output(report_output_id=-1)
        assert "Invalid report output ID" in str(exc_info.value)

        with pytest.raises(Exception) as exc_info:
            service.get_report_output(report_output_id="not_an_int")
        assert "Invalid report output ID" in str(exc_info.value)


class TestUniqueConstraint:
    """Test that the unique constraint on report outputs works correctly."""

    def test_duplicate_report_raises_error(self, test_db):
        """Test that creating duplicate reports is prevented by the database."""
        # GIVEN we create a report
        service.create_report_output(
            simulation_1_id=50,
            simulation_2_id=60,
        )

        # WHEN we try to create an identical report
        # THEN it should raise an error due to unique constraint
        with pytest.raises(Exception) as exc_info:
            # Direct database insert to test constraint
            test_db.query(
                """INSERT INTO report_outputs 
                (simulation_1_id, simulation_2_id, status) 
                VALUES (?, ?, ?)""",
                (50, 60, "pending"),
            )
        
        # The error should mention the unique constraint
        assert "UNIQUE" in str(exc_info.value).upper()


class TestUpdateReportOutput:
    """Test updating report outputs in the database."""

    def test_update_report_output_to_complete(self, test_db, existing_report_record):
        """Test updating a report to complete status with output."""
        # GIVEN an existing pending report
        report_id = existing_report_record["id"]
        test_output = {"result": "success", "data": [1, 2, 3]}

        # WHEN we update it to complete with output
        success = service.update_report_output(
            report_output_id=report_id,
            status="complete",
            output=test_output,
        )

        # THEN the update should succeed
        assert success is True

        # AND the database should reflect the changes
        result = test_db.query(
            "SELECT * FROM report_outputs WHERE id = ?", (report_id,)
        ).fetchone()
        assert result["status"] == "complete"
        assert json.loads(result["output"]) == test_output

    def test_update_report_output_to_error(self, test_db, existing_report_record):
        """Test updating a report to error status with message."""
        # GIVEN an existing pending report
        report_id = existing_report_record["id"]
        error_msg = "Calculation failed due to invalid input"

        # WHEN we update it to error status
        success = service.update_report_output(
            report_output_id=report_id,
            status="error",
            error_message=error_msg,
        )

        # THEN the update should succeed
        assert success is True

        # AND the error should be recorded
        result = test_db.query(
            "SELECT * FROM report_outputs WHERE id = ?", (report_id,)
        ).fetchone()
        assert result["status"] == "error"
        assert result["error_message"] == error_msg

    def test_update_report_output_partial_update(self, test_db, existing_report_record):
        """Test that partial updates work correctly."""
        # GIVEN an existing report
        report_id = existing_report_record["id"]

        # WHEN we update only the status
        success = service.update_report_output(
            report_output_id=report_id,
            status="complete",
        )

        # THEN the update should succeed
        assert success is True

        # AND only the status should change
        result = test_db.query(
            "SELECT * FROM report_outputs WHERE id = ?", (report_id,)
        ).fetchone()
        assert result["status"] == "complete"
        assert result["output"] is None  # Should remain unchanged

    def test_update_report_output_no_fields(self, test_db, existing_report_record):
        """Test that update with no fields returns False."""
        # GIVEN an existing report

        # WHEN we call update with no fields to update
        success = service.update_report_output(
            report_output_id=existing_report_record["id"]
        )

        # THEN it should return False
        assert success is False