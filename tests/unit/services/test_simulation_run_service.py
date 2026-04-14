from policyengine_api.services.simulation_run_service import SimulationRunService
from policyengine_api.services.simulation_service import SimulationService

simulation_run_service = SimulationRunService()
simulation_service = SimulationService()


class TestCreateSimulationRun:
    def test_creates_simulation_runs_with_incrementing_sequence(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_1",
            population_type="household",
            policy_id=1,
        )

        first_run = simulation_run_service.create_simulation_run(
            simulation["id"],
            input_position=1,
            trigger_type="initial",
            simulation_spec_snapshot={"population_id": "household_1"},
            version_manifest={"simulation_cache_version": "s123"},
        )
        second_run = simulation_run_service.create_simulation_run(
            simulation["id"],
            input_position=1,
            trigger_type="rerun",
        )

        assert first_run["run_sequence"] == 1
        assert first_run["trigger_type"] == "initial"
        assert first_run["simulation_spec_snapshot_json"] == {
            "population_id": "household_1"
        }
        assert first_run["simulation_cache_version"] == "s123"
        assert second_run["run_sequence"] == 2
        assert second_run["trigger_type"] == "rerun"


class TestSelectDisplaySimulationRun:
    def test_prefers_active_run(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_2",
            population_type="household",
            policy_id=2,
        )
        latest_successful_run = simulation_run_service.create_simulation_run(
            simulation["id"], trigger_type="initial"
        )
        active_run = simulation_run_service.create_simulation_run(
            simulation["id"], trigger_type="rerun"
        )
        test_db.query(
            """
            UPDATE simulations
            SET active_run_id = ?, latest_successful_run_id = ?
            WHERE id = ?
            """,
            (active_run["id"], latest_successful_run["id"], simulation["id"]),
        )
        updated_simulation = test_db.query(
            "SELECT * FROM simulations WHERE id = ?",
            (simulation["id"],),
        ).fetchone()

        selected_run = simulation_run_service.select_display_run(updated_simulation)

        assert selected_run["id"] == active_run["id"]

    def test_falls_back_to_latest_successful_run(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_3",
            population_type="household",
            policy_id=3,
        )
        successful_run = simulation_run_service.create_simulation_run(
            simulation["id"], trigger_type="initial"
        )
        simulation_run_service.create_simulation_run(
            simulation["id"], trigger_type="rerun"
        )
        test_db.query(
            """
            UPDATE simulations
            SET active_run_id = NULL, latest_successful_run_id = ?
            WHERE id = ?
            """,
            (successful_run["id"], simulation["id"]),
        )
        updated_simulation = test_db.query(
            "SELECT * FROM simulations WHERE id = ?",
            (simulation["id"],),
        ).fetchone()

        selected_run = simulation_run_service.select_display_run(updated_simulation)

        assert selected_run["id"] == successful_run["id"]

    def test_falls_back_to_newest_run_when_no_pointers_exist(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_4",
            population_type="household",
            policy_id=4,
        )
        first_run = simulation_run_service.create_simulation_run(
            simulation["id"], trigger_type="initial"
        )
        newest_run = simulation_run_service.create_simulation_run(
            simulation["id"], trigger_type="rerun"
        )
        test_db.query(
            """
            UPDATE simulations
            SET active_run_id = NULL, latest_successful_run_id = NULL
            WHERE id = ?
            """,
            (simulation["id"],),
        )
        updated_simulation = test_db.query(
            "SELECT * FROM simulations WHERE id = ?",
            (simulation["id"],),
        ).fetchone()

        selected_run = simulation_run_service.select_display_run(updated_simulation)

        assert first_run["run_sequence"] == 1
        assert selected_run["id"] == newest_run["id"]
