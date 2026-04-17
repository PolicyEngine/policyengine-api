import pytest
import json

from policyengine_api.constants import get_report_output_cache_version
from policyengine_api.services.report_output_service import ReportOutputService
from policyengine_api.services.simulation_service import SimulationService

from tests.fixtures.services import report_output_fixtures

pytest_plugins = ("tests.fixtures.services.report_output_fixtures",)

service = ReportOutputService()
simulation_service = SimulationService()


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
        assert (
            result["country_id"]
            == report_output_fixtures.valid_report_data["country_id"]
        )
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
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_report_single_create",
            population_type="household",
            policy_id=1,
        )

        # WHEN we create a report output with one simulation
        created_report = service.create_report_output(
            country_id="us",
            simulation_1_id=simulation["id"],
            simulation_2_id=None,
            year="2025",
        )

        # THEN a valid report record should be returned
        assert created_report is not None
        assert isinstance(created_report, dict)
        assert created_report["id"] > 0
        assert created_report["simulation_1_id"] == simulation["id"]
        assert created_report["simulation_2_id"] is None
        assert created_report["status"] == "pending"
        assert created_report["year"] == "2025"

        # AND the report should be in the database
        result = test_db.query(
            "SELECT * FROM report_outputs WHERE id = ?",
            (created_report["id"],),
        ).fetchone()
        assert result is not None
        assert result["simulation_1_id"] == simulation["id"]
        assert result["simulation_2_id"] is None
        assert result["status"] == "pending"
        assert result["year"] == "2025"

    def test_create_report_output_comparison(self, test_db):
        """Test creating a report output comparing two simulations."""
        # GIVEN an empty database
        simulation_1 = simulation_service.create_simulation(
            country_id="us",
            population_id="household_report_comparison",
            population_type="household",
            policy_id=2,
        )
        simulation_2 = simulation_service.create_simulation(
            country_id="us",
            population_id="household_report_comparison",
            population_type="household",
            policy_id=3,
        )

        # WHEN we create a report output with two simulations
        created_report = service.create_report_output(
            country_id="us",
            simulation_1_id=simulation_1["id"],
            simulation_2_id=simulation_2["id"],
            year="2025",
        )

        # THEN a valid report record should be returned
        assert created_report is not None
        assert created_report["simulation_1_id"] == simulation_1["id"]
        assert created_report["simulation_2_id"] == simulation_2["id"]
        assert created_report["status"] == "pending"
        assert created_report["year"] == "2025"

        # AND the report should be in the database
        result = test_db.query(
            "SELECT * FROM report_outputs WHERE id = ?",
            (created_report["id"],),
        ).fetchone()
        assert result["simulation_1_id"] == simulation_1["id"]
        assert result["simulation_2_id"] == simulation_2["id"]
        assert result["status"] == "pending"
        assert result["year"] == "2025"

    def test_create_report_output_retrieves_correct_id(self, test_db):
        """Test that create_report_output retrieves the correct ID without race conditions."""
        # GIVEN we create multiple reports rapidly

        # WHEN we create reports with different parameters
        created_reports = []
        simulation_ids = []
        for i in range(3):
            simulation_1 = simulation_service.create_simulation(
                country_id="us",
                population_id=f"household_report_id_{i}",
                population_type="household",
                policy_id=100 + i,
            )
            simulation_2 = None
            if i % 2 != 0:
                simulation_2 = simulation_service.create_simulation(
                    country_id="us",
                    population_id=f"household_report_id_{i}",
                    population_type="household",
                    policy_id=200 + i,
                )
            report = service.create_report_output(
                country_id="us",
                simulation_1_id=simulation_1["id"],
                simulation_2_id=None if simulation_2 is None else simulation_2["id"],
                year="2025",
            )
            created_reports.append(report)
            simulation_ids.append(
                (
                    simulation_1["id"],
                    None if simulation_2 is None else simulation_2["id"],
                )
            )

        # THEN all IDs should be unique
        ids = [report["id"] for report in created_reports]
        assert len(set(ids)) == 3

        # AND each report should have the correct data
        for i, report in enumerate(created_reports):
            result = test_db.query(
                "SELECT * FROM report_outputs WHERE id = ?", (report["id"],)
            ).fetchone()
            expected_sim1, expected_sim2 = simulation_ids[i]
            assert result["simulation_1_id"] == expected_sim1
            assert result["simulation_2_id"] == expected_sim2
            assert result["year"] == "2025"

    def test_create_report_output_with_different_year(self, test_db):
        """Test creating a report output with a different year."""
        # GIVEN an empty database
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_report_other_year",
            population_type="household",
            policy_id=4,
        )

        # WHEN we create a report output with year 2024
        created_report = service.create_report_output(
            country_id="us",
            simulation_1_id=simulation["id"],
            simulation_2_id=None,
            year="2024",
        )

        # THEN a valid report record should be returned
        assert created_report is not None
        assert created_report["year"] == "2024"
        assert created_report["simulation_1_id"] == simulation["id"]

        # AND the report should be in the database
        result = test_db.query(
            "SELECT * FROM report_outputs WHERE id = ?",
            (created_report["id"],),
        ).fetchone()
        assert result["year"] == "2024"
        assert result["simulation_1_id"] == simulation["id"]

    def test_create_report_output_populates_dual_write_state(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_report_dual_write",
            population_type="household",
            policy_id=21,
        )

        created_report = service.create_report_output(
            country_id="us",
            simulation_1_id=simulation["id"],
            simulation_2_id=None,
            year="2025",
        )

        stored_report = test_db.query(
            "SELECT * FROM report_outputs WHERE id = ?",
            (created_report["id"],),
        ).fetchone()
        assert stored_report["report_kind"] == "household_single"
        assert stored_report["report_spec_json"] is not None
        assert stored_report["report_spec_schema_version"] == 1
        assert stored_report["report_spec_status"] == "explicit"
        assert stored_report["active_run_id"] is not None
        assert stored_report["latest_successful_run_id"] is None

        run = test_db.query(
            "SELECT * FROM report_output_runs WHERE report_output_id = ?",
            (created_report["id"],),
        ).fetchone()
        assert run is not None
        assert run["status"] == "pending"
        assert run["trigger_type"] == "initial"
        snapshot = run["report_spec_snapshot_json"]
        if isinstance(snapshot, str):
            snapshot = json.loads(snapshot)
        assert snapshot["report_kind"] == "household_single"

    def test_create_report_output_reuses_existing_row_and_bootstraps_dual_write(
        self, test_db
    ):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_existing_report",
            population_type="household",
            policy_id=22,
        )

        test_db.query(
            """
            INSERT INTO report_outputs (
                country_id, simulation_1_id, simulation_2_id, api_version, status, year
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "us",
                simulation["id"],
                None,
                get_report_output_cache_version("us"),
                "pending",
                "2025",
            ),
        )

        created_report = service.create_report_output(
            country_id="us",
            simulation_1_id=simulation["id"],
            simulation_2_id=None,
            year="2025",
        )

        rows = test_db.query(
            """
            SELECT * FROM report_outputs
            WHERE country_id = ? AND simulation_1_id = ? AND simulation_2_id IS NULL AND year = ?
            """,
            ("us", simulation["id"], "2025"),
        ).fetchall()
        assert len(rows) == 1
        assert created_report["id"] == rows[0]["id"]

        run = test_db.query(
            "SELECT * FROM report_output_runs WHERE report_output_id = ?",
            (created_report["id"],),
        ).fetchone()
        assert run is not None

    def test_create_report_output_populates_economy_comparison_report_spec(
        self, test_db
    ):
        baseline_simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="state/ca",
            population_type="geography",
            policy_id=30,
        )
        reform_simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="state/ca",
            population_type="geography",
            policy_id=31,
        )

        created_report = service.create_report_output(
            country_id="us",
            simulation_1_id=baseline_simulation["id"],
            simulation_2_id=reform_simulation["id"],
            year="2025",
        )

        stored_report = test_db.query(
            "SELECT * FROM report_outputs WHERE id = ?",
            (created_report["id"],),
        ).fetchone()
        assert stored_report["report_kind"] == "economy_comparison"
        assert stored_report["report_spec_status"] == "backfilled_assumed"

        report_spec = stored_report["report_spec_json"]
        if isinstance(report_spec, str):
            report_spec = json.loads(report_spec)
        assert report_spec["region"] == "state/ca"
        assert report_spec["baseline_policy_id"] == 30
        assert report_spec["reform_policy_id"] == 31
        assert report_spec["dataset"] == "default"

        run = test_db.query(
            "SELECT * FROM report_output_runs WHERE report_output_id = ?",
            (created_report["id"],),
        ).fetchone()
        assert run is not None
        snapshot = run["report_spec_snapshot_json"]
        if isinstance(snapshot, str):
            snapshot = json.loads(snapshot)
        assert snapshot["report_kind"] == "economy_comparison"
        assert snapshot["region"] == "state/ca"


class TestGetReportOutput:
    """Test retrieving report outputs from the database."""

    def test_get_report_output_existing(self, test_db, existing_report_record):
        """Test retrieving an existing report output."""
        # GIVEN an existing report record

        # WHEN we retrieve the report
        result = service.get_report_output(
            country_id=existing_report_record["country_id"],
            report_output_id=existing_report_record["id"],
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
        result = service.get_report_output(country_id="us", report_output_id=999)

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
        result = service.get_report_output(
            country_id="us", report_output_id=record["id"]
        )

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

        result = service.get_report_output(
            country_id="us", report_output_id=stale_record["id"]
        )
        assert result is not None
        assert result["id"] == stale_record["id"]
        assert result["api_version"] == current_record["api_version"]
        assert result["output"] == current_record["output"]

    def test_get_report_output_creates_current_runtime_row_for_stale_id(self, test_db):
        stale_version = "r0stale1"
        current_version = get_report_output_cache_version("us")
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_stale_runtime_create",
            population_type="household",
            policy_id=5,
        )

        test_db.query(
            """INSERT INTO report_outputs
            (country_id, simulation_1_id, simulation_2_id, status, api_version, year)
            VALUES (?, ?, ?, ?, ?, ?)""",
            ("us", simulation["id"], None, "complete", stale_version, "2025"),
        )

        stale_record = test_db.query(
            "SELECT * FROM report_outputs ORDER BY id DESC LIMIT 1"
        ).fetchone()

        result = service.get_report_output(
            country_id="us", report_output_id=stale_record["id"]
        )

        assert result is not None
        assert result["id"] == stale_record["id"]
        assert result["api_version"] == current_version
        assert result["status"] == "pending"
        assert result["output"] is None

        current_rows = test_db.query(
            "SELECT * FROM report_outputs WHERE country_id = ? AND simulation_1_id = ? AND year = ? ORDER BY id ASC",
            ("us", simulation["id"], "2025"),
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
            service.get_report_output(country_id="us", report_output_id=-1)
        assert "Invalid report output ID" in str(exc_info.value)

        with pytest.raises(Exception) as exc_info:
            service.get_report_output(country_id="us", report_output_id="not_an_int")
        assert "Invalid report output ID" in str(exc_info.value)

    def test_get_report_output_wrong_country_returns_none(
        self, test_db, existing_report_record
    ):
        result = service.get_report_output(
            country_id="uk",
            report_output_id=existing_report_record["id"],
        )

        assert result is None


class TestUniqueConstraint:
    """Test that the unique constraint on report outputs works correctly."""

    def test_duplicate_report_returns_existing(self, test_db):
        """Test that creating duplicate reports returns the existing record."""
        # GIVEN we create a report
        simulation_1 = simulation_service.create_simulation(
            country_id="us",
            population_id="household_duplicate_report",
            population_type="household",
            policy_id=50,
        )
        simulation_2 = simulation_service.create_simulation(
            country_id="us",
            population_id="household_duplicate_report",
            population_type="household",
            policy_id=60,
        )
        first_report = service.create_report_output(
            country_id="us",
            simulation_1_id=simulation_1["id"],
            simulation_2_id=simulation_2["id"],
            year="2025",
        )

        # WHEN we try to create an identical report
        second_report = service.create_report_output(
            country_id="us",
            simulation_1_id=simulation_1["id"],
            simulation_2_id=simulation_2["id"],
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

    def test_update_report_output_updates_dual_write_state(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_report_update",
            population_type="household",
            policy_id=23,
        )
        created_report = service.create_report_output(
            country_id="us",
            simulation_1_id=simulation["id"],
            simulation_2_id=None,
            year="2025",
        )
        output_json = json.dumps({"distribution": [1, 2, 3]})

        success = service.update_report_output(
            country_id="us",
            report_id=created_report["id"],
            status="complete",
            output=output_json,
        )

        assert success is True

        stored_report = test_db.query(
            "SELECT * FROM report_outputs WHERE id = ?",
            (created_report["id"],),
        ).fetchone()
        assert stored_report["active_run_id"] is None
        assert stored_report["latest_successful_run_id"] is not None

        run = test_db.query(
            "SELECT * FROM report_output_runs WHERE report_output_id = ?",
            (created_report["id"],),
        ).fetchone()
        assert run["status"] == "complete"
        assert run["output"] == output_json
        assert run["id"] == stored_report["latest_successful_run_id"]

    def test_update_report_output_bootstraps_missing_run_state(self, test_db):
        simulation_1 = simulation_service.create_simulation(
            country_id="us",
            population_id="household_legacy_report",
            population_type="household",
            policy_id=24,
        )
        simulation_2 = simulation_service.create_simulation(
            country_id="us",
            population_id="household_legacy_report",
            population_type="household",
            policy_id=25,
        )
        test_db.query(
            """
            INSERT INTO report_outputs (
                country_id, simulation_1_id, simulation_2_id, api_version, status, year
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "us",
                simulation_1["id"],
                simulation_2["id"],
                get_report_output_cache_version("us"),
                "pending",
                "2025",
            ),
        )
        report_output = test_db.query(
            "SELECT * FROM report_outputs ORDER BY id DESC LIMIT 1"
        ).fetchone()

        success = service.update_report_output(
            country_id="us",
            report_id=report_output["id"],
            status="error",
            error_message="legacy report failure",
        )

        assert success is True

        stored_report = test_db.query(
            "SELECT * FROM report_outputs WHERE id = ?",
            (report_output["id"],),
        ).fetchone()
        assert stored_report["report_spec_json"] is not None
        assert stored_report["active_run_id"] is None
        assert stored_report["latest_successful_run_id"] is None

        run = test_db.query(
            "SELECT * FROM report_output_runs WHERE report_output_id = ?",
            (report_output["id"],),
        ).fetchone()
        assert run is not None
        assert run["status"] == "error"
        assert run["error_message"] == "legacy report failure"

    def test_update_report_output_keeps_invalid_legacy_linkage_working(self, test_db):
        simulation_1 = simulation_service.create_simulation(
            country_id="us",
            population_id="us",
            population_type="geography",
            policy_id=26,
        )
        simulation_2 = simulation_service.create_simulation(
            country_id="us",
            population_id="state/ca",
            population_type="geography",
            policy_id=27,
        )
        test_db.query(
            """
            INSERT INTO report_outputs (
                country_id, simulation_1_id, simulation_2_id, api_version, status, year
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "us",
                simulation_1["id"],
                simulation_2["id"],
                get_report_output_cache_version("us"),
                "pending",
                "2025",
            ),
        )
        report_output = test_db.query(
            "SELECT * FROM report_outputs ORDER BY id DESC LIMIT 1"
        ).fetchone()

        success = service.update_report_output(
            country_id="us",
            report_id=report_output["id"],
            status="complete",
            output=json.dumps({"budget": {"budgetary_impact": 1}}),
        )

        assert success is True

        stored_report = test_db.query(
            "SELECT * FROM report_outputs WHERE id = ?",
            (report_output["id"],),
        ).fetchone()
        assert stored_report["report_spec_json"] is None

        run = test_db.query(
            "SELECT * FROM report_output_runs WHERE report_output_id = ?",
            (report_output["id"],),
        ).fetchone()
        assert run is not None
        assert run["report_spec_snapshot_json"] is None

    def test_update_report_output_stale_id_updates_only_stale_lineage_run(
        self, test_db
    ):
        stale_version = "r0stale1"
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_stale_lineage",
            population_type="household",
            policy_id=32,
        )
        test_db.query(
            """
            INSERT INTO report_outputs
            (country_id, simulation_1_id, simulation_2_id, status, api_version, year)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("us", simulation["id"], None, "pending", stale_version, "2025"),
        )
        stale_report = test_db.query(
            "SELECT * FROM report_outputs ORDER BY id DESC LIMIT 1"
        ).fetchone()

        success = service.update_report_output(
            country_id="us",
            report_id=stale_report["id"],
            status="complete",
            output=json.dumps({"result": "stale"}),
        )

        assert success is True

        rows = test_db.query(
            """
            SELECT * FROM report_outputs
            WHERE country_id = ? AND simulation_1_id = ? AND year = ?
            ORDER BY id ASC
            """,
            ("us", simulation["id"], "2025"),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["id"] == stale_report["id"]
        assert rows[0]["status"] == "complete"

        runs = test_db.query(
            """
            SELECT * FROM report_output_runs
            WHERE report_output_id = ?
            ORDER BY run_sequence ASC
            """,
            (stale_report["id"],),
        ).fetchall()
        assert len(runs) == 1
        assert runs[0]["status"] == "complete"
        assert runs[0]["output"] == json.dumps({"result": "stale"})

    def test_update_report_output_does_not_append_extra_run_for_legacy_patch_traffic(
        self, test_db
    ):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_report_single_run",
            population_type="household",
            policy_id=33,
        )
        created_report = service.create_report_output(
            country_id="us",
            simulation_1_id=simulation["id"],
            simulation_2_id=None,
            year="2025",
        )

        first_run = test_db.query(
            "SELECT * FROM report_output_runs WHERE report_output_id = ?",
            (created_report["id"],),
        ).fetchone()
        assert first_run is not None

        success = service.update_report_output(
            country_id="us",
            report_id=created_report["id"],
            status="complete",
            output=json.dumps({"distribution": [4, 5, 6]}),
        )

        assert success is True

        runs = test_db.query(
            """
            SELECT * FROM report_output_runs
            WHERE report_output_id = ?
            ORDER BY run_sequence ASC
            """,
            (created_report["id"],),
        ).fetchall()
        assert len(runs) == 1
        assert runs[0]["id"] == first_run["id"]
        assert runs[0]["status"] == "complete"

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

    def test_create_report_output_rolls_back_parent_insert_on_dual_write_failure(
        self, test_db, monkeypatch
    ):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_report_create_rollback",
            population_type="household",
            policy_id=34,
        )

        def fail_dual_write(tx, report_output_id, *, country_id=None, **kwargs):
            raise RuntimeError("dual write sync failed")

        monkeypatch.setattr(
            service,
            "_ensure_report_output_dual_write_state_in_transaction",
            fail_dual_write,
        )

        with pytest.raises(RuntimeError, match="dual write sync failed"):
            service.create_report_output(
                country_id="us",
                simulation_1_id=simulation["id"],
                simulation_2_id=None,
                year="2025",
            )

        rows = test_db.query(
            """
            SELECT * FROM report_outputs
            WHERE country_id = ? AND simulation_1_id = ? AND simulation_2_id IS NULL AND year = ?
            """,
            ("us", simulation["id"], "2025"),
        ).fetchall()
        assert rows == []

    def test_update_report_output_rolls_back_parent_update_on_dual_write_failure(
        self, test_db, monkeypatch
    ):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_report_update_rollback",
            population_type="household",
            policy_id=35,
        )
        created_report = service.create_report_output(
            country_id="us",
            simulation_1_id=simulation["id"],
            simulation_2_id=None,
            year="2025",
        )

        def fail_dual_write(tx, report_output_id, *, country_id=None, **kwargs):
            raise RuntimeError("dual write sync failed")

        monkeypatch.setattr(
            service,
            "_ensure_report_output_dual_write_state_in_transaction",
            fail_dual_write,
        )

        with pytest.raises(RuntimeError, match="dual write sync failed"):
            service.update_report_output(
                country_id="us",
                report_id=created_report["id"],
                status="complete",
                output=json.dumps({"rolled_back": True}),
            )

        stored_report = test_db.query(
            "SELECT * FROM report_outputs WHERE id = ?",
            (created_report["id"],),
        ).fetchone()
        assert stored_report["status"] == "pending"
        assert stored_report["output"] is None

        run = test_db.query(
            "SELECT * FROM report_output_runs WHERE report_output_id = ?",
            (created_report["id"],),
        ).fetchone()
        assert run is not None
        assert run["status"] == "pending"
        assert run["output"] is None

    def test_ensure_report_output_dual_write_state_bootstraps_linked_simulations(
        self, test_db
    ):
        test_db.query(
            """
            INSERT INTO simulations (
                country_id, api_version, population_id, population_type, policy_id, status
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "us",
                "us-system-1.0.0",
                "household_stage5_linked",
                "household",
                36,
                "pending",
            ),
        )
        simulation_1 = test_db.query(
            "SELECT * FROM simulations ORDER BY id DESC LIMIT 1"
        ).fetchone()

        test_db.query(
            """
            INSERT INTO simulations (
                country_id, api_version, population_id, population_type, policy_id, status
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "us",
                "us-system-1.0.0",
                "household_stage5_linked",
                "household",
                37,
                "pending",
            ),
        )
        simulation_2 = test_db.query(
            "SELECT * FROM simulations ORDER BY id DESC LIMIT 1"
        ).fetchone()

        test_db.query(
            """
            INSERT INTO report_outputs (
                country_id, simulation_1_id, simulation_2_id, api_version, status, year
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "us",
                simulation_1["id"],
                simulation_2["id"],
                get_report_output_cache_version("us"),
                "pending",
                "2025",
            ),
        )
        report_output = test_db.query(
            "SELECT * FROM report_outputs ORDER BY id DESC LIMIT 1"
        ).fetchone()

        synced_report = service.ensure_report_output_dual_write_state(
            report_output["id"],
            country_id="us",
        )

        assert synced_report["active_run_id"] is not None

        stored_simulation_1 = test_db.query(
            "SELECT * FROM simulations WHERE id = ?",
            (simulation_1["id"],),
        ).fetchone()
        stored_simulation_2 = test_db.query(
            "SELECT * FROM simulations WHERE id = ?",
            (simulation_2["id"],),
        ).fetchone()
        assert stored_simulation_1["simulation_spec_json"] is not None
        assert stored_simulation_1["active_run_id"] is not None
        assert stored_simulation_2["simulation_spec_json"] is not None
        assert stored_simulation_2["active_run_id"] is not None

        simulation_1_run = test_db.query(
            "SELECT * FROM simulation_runs WHERE simulation_id = ?",
            (simulation_1["id"],),
        ).fetchone()
        simulation_2_run = test_db.query(
            "SELECT * FROM simulation_runs WHERE simulation_id = ?",
            (simulation_2["id"],),
        ).fetchone()
        assert simulation_1_run is not None
        assert simulation_2_run is not None
