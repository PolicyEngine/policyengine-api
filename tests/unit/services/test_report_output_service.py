import pytest
import json

from policyengine_api.constants import get_report_output_cache_version
from policyengine_api.services.report_output_service import ReportOutputService

pytest_plugins = ("tests.fixtures.services.report_output_fixtures",)

service = ReportOutputService()


class TestFindExistingReportOutput:
    """Test finding existing report outputs in the database."""

    def test_find_existing_report_output_found(self, test_db, existing_report_record):
        """Test finding an existing report output."""
        # GIVEN an existing report record (from fixture)

        # WHEN we search for a report with matching simulation IDs
        result = service.find_existing_report_output(
            country_id=existing_report_record["country_id"],
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
            country_id="us",
            simulation_1_id=999,
            simulation_2_id=888,
            year="2025",
        )

        # THEN None should be returned
        assert result is None

    def test_find_existing_report_output_with_null_simulation2(self, test_db):
        """Test finding reports where simulation_2_id is NULL."""
        api_version = get_report_output_cache_version("us")
        # GIVEN a report with NULL simulation_2_id
        test_db.query(
            "INSERT INTO report_outputs (country_id, simulation_1_id, simulation_2_id, status, api_version, year) VALUES (?, ?, ?, ?, ?, ?)",
            ("us", 100, None, "complete", api_version, "2025"),
        )

        # WHEN we search for it
        result = service.find_existing_report_output(
            country_id="us",
            simulation_1_id=100,
            simulation_2_id=None,
            year="2025",
        )

        # THEN we should find it
        assert result is not None
        assert result["simulation_1_id"] == 100
        assert result["simulation_2_id"] is None
        assert result["year"] == "2025"

    def test_find_existing_report_output_with_year(self, test_db):
        """Test finding reports with different years."""
        api_version = get_report_output_cache_version("us")
        # GIVEN reports with different years for the same simulation
        test_db.query(
            "INSERT INTO report_outputs (country_id, simulation_1_id, simulation_2_id, status, api_version, year) VALUES (?, ?, ?, ?, ?, ?)",
            ("us", 101, None, "complete", api_version, "2025"),
        )
        test_db.query(
            "INSERT INTO report_outputs (country_id, simulation_1_id, simulation_2_id, status, api_version, year) VALUES (?, ?, ?, ?, ?, ?)",
            ("us", 101, None, "complete", api_version, "2024"),
        )

        # WHEN we search for the 2025 report
        result_2025 = service.find_existing_report_output(
            country_id="us",
            simulation_1_id=101,
            simulation_2_id=None,
            year="2025",
        )

        # THEN we should find the 2025 report
        assert result_2025 is not None
        assert result_2025["simulation_1_id"] == 101
        assert result_2025["year"] == "2025"

        # WHEN we search for the 2024 report
        result_2024 = service.find_existing_report_output(
            country_id="us",
            simulation_1_id=101,
            simulation_2_id=None,
            year="2024",
        )

        # THEN we should find the 2024 report
        assert result_2024 is not None
        assert result_2024["simulation_1_id"] == 101
        assert result_2024["year"] == "2024"

        # AND the two reports should have different IDs
        assert result_2025["id"] != result_2024["id"]

    def test_find_existing_report_output_ignores_stale_runtime_version(self, test_db):
        current_version = get_report_output_cache_version("us")
        stale_version = "r0stale1"
        assert stale_version != current_version

        test_db.query(
            "INSERT INTO report_outputs (country_id, simulation_1_id, simulation_2_id, status, api_version, year) VALUES (?, ?, ?, ?, ?, ?)",
            ("us", 102, None, "complete", stale_version, "2025"),
        )

        result = service.find_existing_report_output(
            country_id="us",
            simulation_1_id=102,
            simulation_2_id=None,
            year="2025",
        )

        assert result is None


class TestCreateReportOutput:
    """Test creating new report outputs in the database."""

    def test_create_report_output_single_simulation(self, test_db):
        """Test creating a report output with a single simulation."""
        # GIVEN an empty database

        # WHEN we create a report output with one simulation
        created_report = service.create_report_output(
            country_id="us",
            simulation_1_id=1,
            simulation_2_id=None,
            year="2025",
        )

        # THEN a valid report record should be returned
        assert created_report is not None
        assert isinstance(created_report, dict)
        assert created_report["id"] > 0
        assert created_report["simulation_1_id"] == 1
        assert created_report["simulation_2_id"] is None
        assert created_report["status"] == "pending"
        assert created_report["year"] == "2025"

        # AND the report should be in the database
        result = test_db.query(
            "SELECT * FROM report_outputs WHERE id = ?",
            (created_report["id"],),
        ).fetchone()
        assert result is not None
        assert result["simulation_1_id"] == 1
        assert result["simulation_2_id"] is None
        assert result["status"] == "pending"
        assert result["year"] == "2025"

    def test_create_report_output_comparison(self, test_db):
        """Test creating a report output comparing two simulations."""
        # GIVEN an empty database

        # WHEN we create a report output with two simulations
        created_report = service.create_report_output(
            country_id="us",
            simulation_1_id=1,
            simulation_2_id=2,
            year="2025",
        )

        # THEN a valid report record should be returned
        assert created_report is not None
        assert created_report["simulation_1_id"] == 1
        assert created_report["simulation_2_id"] == 2
        assert created_report["status"] == "pending"
        assert created_report["year"] == "2025"

        # AND the report should be in the database
        result = test_db.query(
            "SELECT * FROM report_outputs WHERE id = ?",
            (created_report["id"],),
        ).fetchone()
        assert result["simulation_1_id"] == 1
        assert result["simulation_2_id"] == 2
        assert result["status"] == "pending"
        assert result["year"] == "2025"

    def test_create_report_output_retrieves_correct_id(self, test_db):
        """Test that create_report_output retrieves the correct ID without race conditions."""
        # GIVEN we create multiple reports rapidly

        # WHEN we create reports with different parameters
        created_reports = []
        for i in range(3):
            report = service.create_report_output(
                country_id="us",
                simulation_1_id=i + 1,
                simulation_2_id=None if i % 2 == 0 else i + 10,
                year="2025",
            )
            created_reports.append(report)

        # THEN all IDs should be unique
        ids = [report["id"] for report in created_reports]
        assert len(set(ids)) == 3

        # AND each report should have the correct data
        for i, report in enumerate(created_reports):
            result = test_db.query(
                "SELECT * FROM report_outputs WHERE id = ?", (report["id"],)
            ).fetchone()
            assert result["simulation_1_id"] == i + 1
            expected_sim2 = None if i % 2 == 0 else i + 10
            assert result["simulation_2_id"] == expected_sim2
            assert result["year"] == "2025"

    def test_create_report_output_with_different_year(self, test_db):
        """Test creating a report output with a different year."""
        # GIVEN an empty database

        # WHEN we create a report output with year 2024
        created_report = service.create_report_output(
            country_id="us",
            simulation_1_id=200,
            simulation_2_id=None,
            year="2024",
        )

        # THEN a valid report record should be returned
        assert created_report is not None
        assert created_report["year"] == "2024"
        assert created_report["simulation_1_id"] == 200

        # AND the report should be in the database
        result = test_db.query(
            "SELECT * FROM report_outputs WHERE id = ?",
            (created_report["id"],),
        ).fetchone()
        assert result["year"] == "2024"
        assert result["simulation_1_id"] == 200


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
            (country_id, simulation_1_id, simulation_2_id, status, output, api_version, year)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                "us",
                1,
                None,
                "complete",
                json.dumps(test_output),
                get_report_output_cache_version("us"),
                "2025",
            ),
        )

        # Get the ID of the inserted record
        record = test_db.query(
            "SELECT id FROM report_outputs ORDER BY id DESC LIMIT 1"
        ).fetchone()

        # WHEN we retrieve the report
        result = service.get_report_output(report_output_id=record["id"])

        # THEN the output should be returned as JSON string (not parsed)
        assert result["output"] == json.dumps(test_output)
        assert result["year"] == "2025"
        # Frontend will parse this string

    def test_get_report_output_resolves_stale_id_to_current_runtime_row(self, test_db):
        stale_output = {
            "budget": {"budgetary_impact": 1},
            "congressional_district_impact": {
                "districts": [
                    {
                        "district": "AL-01",
                        "average_household_income_change": 120,
                        "relative_household_income_change": 0.01,
                    }
                ]
            },
        }
        test_db.query(
            """INSERT INTO report_outputs
            (country_id, simulation_1_id, simulation_2_id, status, output, api_version, year)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                "us",
                2,
                None,
                "complete",
                json.dumps(stale_output),
                "r0stale1",
                "2025",
            ),
        )

        stale_record = test_db.query(
            "SELECT * FROM report_outputs ORDER BY id DESC LIMIT 1"
        ).fetchone()

        current_version = get_report_output_cache_version("us")
        test_db.query(
            """INSERT INTO report_outputs
            (country_id, simulation_1_id, simulation_2_id, status, output, api_version, year)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                "us",
                2,
                None,
                "complete",
                json.dumps({"budget": {"budgetary_impact": 2}}),
                current_version,
                "2025",
            ),
        )

        current_record = test_db.query(
            "SELECT * FROM report_outputs ORDER BY id DESC LIMIT 1"
        ).fetchone()

        result = service.get_report_output(report_output_id=stale_record["id"])
        assert result is not None
        assert result["id"] == stale_record["id"]
        assert result["api_version"] == current_record["api_version"]
        assert result["output"] == current_record["output"]

    def test_get_report_output_creates_current_runtime_row_for_stale_id(self, test_db):
        stale_version = "r0stale1"
        current_version = get_report_output_cache_version("us")

        test_db.query(
            """INSERT INTO report_outputs
            (country_id, simulation_1_id, simulation_2_id, status, api_version, year)
            VALUES (?, ?, ?, ?, ?, ?)""",
            ("us", 3, None, "complete", stale_version, "2025"),
        )

        stale_record = test_db.query(
            "SELECT * FROM report_outputs ORDER BY id DESC LIMIT 1"
        ).fetchone()

        result = service.get_report_output(report_output_id=stale_record["id"])

        assert result is not None
        assert result["id"] == stale_record["id"]
        assert result["api_version"] == current_version
        assert result["status"] == "pending"
        assert result["output"] is None

        current_rows = test_db.query(
            "SELECT * FROM report_outputs WHERE country_id = ? AND simulation_1_id = ? AND year = ? ORDER BY id ASC",
            ("us", 3, "2025"),
        ).fetchall()
        assert len(current_rows) == 2
        assert current_rows[0]["api_version"] == stale_version
        assert current_rows[1]["api_version"] == current_version

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

    def test_duplicate_report_returns_existing(self, test_db):
        """Test that creating duplicate reports returns the existing record."""
        # GIVEN we create a report
        first_report = service.create_report_output(
            country_id="us",
            simulation_1_id=50,
            simulation_2_id=60,
            year="2025",
        )

        # WHEN we try to create an identical report
        second_report = service.create_report_output(
            country_id="us",
            simulation_1_id=50,
            simulation_2_id=60,
            year="2025",
        )

        # THEN the same report should be returned (no duplicate created)
        assert first_report["id"] == second_report["id"]
        assert first_report["country_id"] == second_report["country_id"]
        assert first_report["simulation_1_id"] == second_report["simulation_1_id"]
        assert first_report["simulation_2_id"] == second_report["simulation_2_id"]
        assert first_report["year"] == second_report["year"]


class TestUpdateReportOutput:
    """Test updating report outputs in the database."""

    def test_update_report_output_to_complete(self, test_db, existing_report_record):
        """Test updating a report to complete status with output."""
        # GIVEN an existing pending report
        report_id = existing_report_record["id"]
        test_output = {"result": "success", "data": [1, 2, 3]}
        test_output_json = json.dumps(test_output)

        # WHEN we update it to complete with output (as JSON string)
        success = service.update_report_output(
            country_id=existing_report_record["country_id"],
            report_id=report_id,
            status="complete",
            output=test_output_json,
        )

        # THEN the update should succeed
        assert success is True

        # AND the database should reflect the changes
        result = test_db.query(
            "SELECT * FROM report_outputs WHERE id = ?", (report_id,)
        ).fetchone()
        assert result["status"] == "complete"
        assert result["output"] == test_output_json

    def test_update_report_output_to_error(self, test_db, existing_report_record):
        """Test updating a report to error status with message."""
        # GIVEN an existing pending report
        report_id = existing_report_record["id"]
        error_msg = "Calculation failed due to invalid input"

        # WHEN we update it to error status
        success = service.update_report_output(
            country_id=existing_report_record["country_id"],
            report_id=report_id,
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
            country_id=existing_report_record["country_id"],
            report_id=report_id,
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

    def test_update_report_output_no_fields_returns_false(
        self, test_db, existing_report_record
    ):
        success = service.update_report_output(
            country_id=existing_report_record["country_id"],
            report_id=existing_report_record["id"],
        )

        assert success is False

    def test_update_report_output_stale_id_keeps_stale_output_quarantined(
        self, test_db
    ):
        stale_version = "r0stale1"
        output_json = json.dumps({"result": "fresh"})

        test_db.query(
            """INSERT INTO report_outputs
            (country_id, simulation_1_id, simulation_2_id, status, api_version, year)
            VALUES (?, ?, ?, ?, ?, ?)""",
            ("us", 4, None, "pending", stale_version, "2025"),
        )

        stale_record = test_db.query(
            "SELECT * FROM report_outputs ORDER BY id DESC LIMIT 1"
        ).fetchone()

        success = service.update_report_output(
            country_id="us",
            report_id=stale_record["id"],
            status="complete",
            output=output_json,
        )

        assert success is True

        rows = test_db.query(
            "SELECT * FROM report_outputs WHERE country_id = ? AND simulation_1_id = ? AND year = ? ORDER BY id ASC",
            ("us", 4, "2025"),
        ).fetchall()

        assert len(rows) == 1
        assert rows[0]["id"] == stale_record["id"]
        assert rows[0]["api_version"] == stale_version
        assert rows[0]["status"] == "complete"
        assert rows[0]["output"] == output_json


class TestResetReportOutput:
    def test_reset_report_output_clears_output_and_error(self, test_db):
        output_json = json.dumps({"result": "complete"})
        error_message = "old error"

        test_db.query(
            """INSERT INTO report_outputs
            (country_id, simulation_1_id, simulation_2_id, status, output, error_message, api_version, year)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "us",
                11,
                None,
                "complete",
                output_json,
                error_message,
                get_report_output_cache_version("us"),
                "2025",
            ),
        )

        report = test_db.query(
            "SELECT * FROM report_outputs ORDER BY id DESC LIMIT 1"
        ).fetchone()

        success = service.reset_report_output(
            country_id="us",
            report_id=report["id"],
        )

        assert success is True

        reset_report = test_db.query(
            "SELECT * FROM report_outputs WHERE id = ?",
            (report["id"],),
        ).fetchone()
        assert reset_report["status"] == "pending"
        assert reset_report["output"] is None
        assert reset_report["error_message"] is None

    def test_reset_report_output_rejects_wrong_country(self, test_db):
        test_db.query(
            """INSERT INTO report_outputs
            (country_id, simulation_1_id, simulation_2_id, status, api_version, year)
            VALUES (?, ?, ?, ?, ?, ?)""",
            ("us", 12, None, "complete", get_report_output_cache_version("us"), "2025"),
        )

        report = test_db.query(
            "SELECT * FROM report_outputs ORDER BY id DESC LIMIT 1"
        ).fetchone()

        with pytest.raises(Exception, match="does not belong to country uk"):
            service.reset_report_output(country_id="uk", report_id=report["id"])
