import pytest

from policyengine_api.services.report_output_service import ReportOutputService
from policyengine_api.services.report_run_service import ReportRunService
from policyengine_api.services.simulation_service import SimulationService

report_output_service = ReportOutputService()
report_run_service = ReportRunService()
simulation_service = SimulationService()


class TestCreateReportOutputRun:
    def test_creates_report_runs_with_incrementing_sequence(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_1",
            population_type="household",
            policy_id=1,
        )
        report_output = report_output_service.create_report_output(
            country_id="us",
            simulation_1_id=simulation["id"],
            simulation_2_id=None,
            year="2025",
        )

        first_run = report_run_service.create_report_output_run(
            report_output["id"],
            trigger_type="initial",
            report_spec_snapshot={"country_id": "us"},
            version_manifest={
                "country_package_version": "us-1.0.0",
                "report_cache_version": "r123",
            },
        )
        second_run = report_run_service.create_report_output_run(
            report_output["id"],
            trigger_type="rerun",
        )

        assert first_run["run_sequence"] == 1
        assert first_run["trigger_type"] == "initial"
        assert first_run["report_spec_snapshot_json"] == {"country_id": "us"}
        assert first_run["country_package_version"] == "us-1.0.0"
        assert first_run["report_cache_version"] == "r123"
        assert second_run["run_sequence"] == 2
        assert second_run["trigger_type"] == "rerun"

    def test_lists_report_runs_in_sequence_order(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_3",
            population_type="household",
            policy_id=3,
        )
        report_output = report_output_service.create_report_output(
            country_id="us",
            simulation_1_id=simulation["id"],
            simulation_2_id=None,
            year="2025",
        )
        report_run_service.create_report_output_run(
            report_output["id"], trigger_type="initial"
        )
        report_run_service.create_report_output_run(
            report_output["id"], trigger_type="rerun"
        )

        runs = report_run_service.list_report_output_runs(report_output["id"])

        assert [run["run_sequence"] for run in runs] == [1, 2]

    def test_allocates_run_sequence_transactionally(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_7",
            population_type="household",
            policy_id=7,
        )
        report_output = report_output_service.create_report_output(
            country_id="us",
            simulation_1_id=simulation["id"],
            simulation_2_id=None,
            year="2025",
        )

        first_run = report_run_service.create_report_output_run(
            report_output["id"], trigger_type="initial"
        )
        second_run = report_run_service.create_report_output_run(
            report_output["id"], trigger_type="rerun"
        )

        assert first_run["run_sequence"] == 1
        assert second_run["run_sequence"] == 2

    def test_raises_when_parent_report_output_is_missing(self, test_db):
        with pytest.raises(ValueError) as exc_info:
            report_run_service.create_report_output_run(999999, trigger_type="initial")

        assert "Report output #999999 not found" in str(exc_info.value)


class TestSelectDisplayReportRun:
    def test_prefers_active_run(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_4",
            population_type="household",
            policy_id=4,
        )
        report_output = report_output_service.create_report_output(
            country_id="us",
            simulation_1_id=simulation["id"],
            simulation_2_id=None,
            year="2025",
        )
        latest_successful_run = report_run_service.create_report_output_run(
            report_output["id"], trigger_type="initial"
        )
        active_run = report_run_service.create_report_output_run(
            report_output["id"], trigger_type="rerun"
        )
        test_db.query(
            """
            UPDATE report_outputs
            SET active_run_id = ?, latest_successful_run_id = ?
            WHERE id = ?
            """,
            (active_run["id"], latest_successful_run["id"], report_output["id"]),
        )
        updated_report_output = test_db.query(
            "SELECT * FROM report_outputs WHERE id = ?",
            (report_output["id"],),
        ).fetchone()

        selected_run = report_run_service.select_display_run(updated_report_output)

        assert selected_run["id"] == active_run["id"]

    def test_falls_back_to_latest_successful_run(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_5",
            population_type="household",
            policy_id=5,
        )
        report_output = report_output_service.create_report_output(
            country_id="us",
            simulation_1_id=simulation["id"],
            simulation_2_id=None,
            year="2025",
        )
        successful_run = report_run_service.create_report_output_run(
            report_output["id"], trigger_type="initial"
        )
        report_run_service.create_report_output_run(
            report_output["id"], trigger_type="rerun"
        )
        test_db.query(
            """
            UPDATE report_outputs
            SET active_run_id = NULL, latest_successful_run_id = ?
            WHERE id = ?
            """,
            (successful_run["id"], report_output["id"]),
        )
        updated_report_output = test_db.query(
            "SELECT * FROM report_outputs WHERE id = ?",
            (report_output["id"],),
        ).fetchone()

        selected_run = report_run_service.select_display_run(updated_report_output)

        assert selected_run["id"] == successful_run["id"]

    def test_falls_back_when_active_run_pointer_is_stale(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_5a",
            population_type="household",
            policy_id=5,
        )
        report_output = report_output_service.create_report_output(
            country_id="us",
            simulation_1_id=simulation["id"],
            simulation_2_id=None,
            year="2025",
        )
        successful_run = report_run_service.create_report_output_run(
            report_output["id"], trigger_type="initial"
        )
        test_db.query(
            """
            UPDATE report_outputs
            SET active_run_id = ?, latest_successful_run_id = ?
            WHERE id = ?
            """,
            ("missing-run", successful_run["id"], report_output["id"]),
        )
        updated_report_output = test_db.query(
            "SELECT * FROM report_outputs WHERE id = ?",
            (report_output["id"],),
        ).fetchone()

        selected_run = report_run_service.select_display_run(updated_report_output)

        assert selected_run["id"] == successful_run["id"]

    def test_falls_back_to_newest_run_when_no_pointers_exist(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_6",
            population_type="household",
            policy_id=6,
        )
        report_output = report_output_service.create_report_output(
            country_id="us",
            simulation_1_id=simulation["id"],
            simulation_2_id=None,
            year="2025",
        )
        first_run = report_run_service.create_report_output_run(
            report_output["id"], trigger_type="initial"
        )
        newest_run = report_run_service.create_report_output_run(
            report_output["id"], trigger_type="rerun"
        )
        test_db.query(
            """
            UPDATE report_outputs
            SET active_run_id = NULL, latest_successful_run_id = NULL
            WHERE id = ?
            """,
            (report_output["id"],),
        )
        updated_report_output = test_db.query(
            "SELECT * FROM report_outputs WHERE id = ?",
            (report_output["id"],),
        ).fetchone()

        selected_run = report_run_service.select_display_run(updated_report_output)

        assert first_run["run_sequence"] == 1
        assert selected_run["id"] == newest_run["id"]

    def test_falls_back_to_newest_run_when_latest_successful_pointer_is_stale(
        self, test_db
    ):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_6a",
            population_type="household",
            policy_id=6,
        )
        report_output = report_output_service.create_report_output(
            country_id="us",
            simulation_1_id=simulation["id"],
            simulation_2_id=None,
            year="2025",
        )
        newest_run = report_run_service.create_report_output_run(
            report_output["id"], trigger_type="rerun"
        )
        test_db.query(
            """
            UPDATE report_outputs
            SET active_run_id = NULL, latest_successful_run_id = ?
            WHERE id = ?
            """,
            ("missing-run", report_output["id"]),
        )
        updated_report_output = test_db.query(
            "SELECT * FROM report_outputs WHERE id = ?",
            (report_output["id"],),
        ).fetchone()

        selected_run = report_run_service.select_display_run(updated_report_output)

        assert selected_run["id"] == newest_run["id"]
