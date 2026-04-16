from sqlalchemy.engine.row import Row

from policyengine_api.data import database
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.services.simulation_spec_service import (
    SimulationSpec,
    SimulationSpecService,
)
from policyengine_api.services.simulation_run_service import SimulationRunService
from policyengine_api.services.run_sync_utils import (
    determine_parent_pointers,
    serialize_json_field,
)


class SimulationService:
    def __init__(self):
        self.simulation_spec_service = SimulationSpecService()
        self.simulation_run_service = SimulationRunService()

    def _get_simulation_row(self, simulation_id: int) -> dict | None:
        row: Row | None = database.query(
            "SELECT * FROM simulations WHERE id = ?",
            (simulation_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def _build_version_manifest(self, simulation: dict) -> dict[str, str | None]:
        return {
            "country_package_version": simulation.get("api_version"),
            "policyengine_version": None,
            "data_version": None,
            "runtime_app_name": None,
            "simulation_cache_version": None,
        }

    def _get_runs_descending(self, simulation_id: int) -> list[dict]:
        return sorted(
            self.simulation_run_service.list_simulation_runs(simulation_id),
            key=lambda run: run["run_sequence"],
            reverse=True,
        )

    def _select_mutable_run(
        self, simulation: dict, runs_descending: list[dict]
    ) -> dict | None:
        active_run_id = simulation.get("active_run_id")
        if active_run_id:
            active_run = self.simulation_run_service.get_simulation_run(active_run_id)
            if active_run is not None:
                return active_run
        return runs_descending[0] if runs_descending else None

    def _upsert_simulation_spec(self, simulation: dict) -> SimulationSpec:
        expected_spec = self.simulation_spec_service.build_simulation_spec(simulation)
        existing_spec = None

        try:
            existing_spec = self.simulation_spec_service.get_simulation_spec(
                simulation["id"]
            )
        except ValueError:
            existing_spec = None

        if (
            existing_spec is None
            or existing_spec.model_dump() != expected_spec.model_dump()
        ):
            self.simulation_spec_service.set_simulation_spec(
                simulation_id=simulation["id"],
                simulation_spec=expected_spec,
            )

        return expected_spec

    def _run_matches_parent(
        self,
        run: dict,
        simulation: dict,
        simulation_spec: SimulationSpec,
    ) -> bool:
        version_manifest = self._build_version_manifest(simulation)
        return (
            run["status"] == simulation["status"]
            and run.get("output") == simulation.get("output")
            and run.get("error_message") == simulation.get("error_message")
            and run.get("simulation_spec_snapshot_json") == simulation_spec.model_dump()
            and run.get("country_package_version")
            == version_manifest["country_package_version"]
            and run.get("policyengine_version")
            == version_manifest["policyengine_version"]
            and run.get("data_version") == version_manifest["data_version"]
            and run.get("runtime_app_name") == version_manifest["runtime_app_name"]
            and run.get("simulation_cache_version")
            == version_manifest["simulation_cache_version"]
        )

    def _update_simulation_run(
        self,
        run_id: str,
        simulation: dict,
        simulation_spec: SimulationSpec,
    ) -> None:
        version_manifest = self._build_version_manifest(simulation)
        database.query(
            """
            UPDATE simulation_runs
            SET status = ?, output = ?, error_message = ?,
                simulation_spec_snapshot_json = ?, country_package_version = ?,
                policyengine_version = ?, data_version = ?, runtime_app_name = ?,
                simulation_cache_version = ?
            WHERE id = ?
            """,
            (
                simulation["status"],
                serialize_json_field(simulation.get("output")),
                simulation.get("error_message"),
                simulation_spec.model_dump_json(),
                version_manifest["country_package_version"],
                version_manifest["policyengine_version"],
                version_manifest["data_version"],
                version_manifest["runtime_app_name"],
                version_manifest["simulation_cache_version"],
                run_id,
            ),
        )

    def _sync_parent_pointers(
        self, simulation: dict, runs_descending: list[dict]
    ) -> None:
        desired_active_run_id, desired_latest_successful_run_id = (
            determine_parent_pointers(simulation["status"], runs_descending)
        )
        if (
            simulation.get("active_run_id") == desired_active_run_id
            and simulation.get("latest_successful_run_id")
            == desired_latest_successful_run_id
        ):
            return

        database.query(
            """
            UPDATE simulations
            SET active_run_id = ?, latest_successful_run_id = ?
            WHERE id = ?
            """,
            (
                desired_active_run_id,
                desired_latest_successful_run_id,
                simulation["id"],
            ),
        )

    def ensure_simulation_dual_write_state(self, simulation_id: int) -> dict:
        simulation = self._get_simulation_row(simulation_id)
        if simulation is None:
            raise ValueError(f"Simulation #{simulation_id} not found")

        simulation_spec = self._upsert_simulation_spec(simulation)
        runs_descending = self._get_runs_descending(simulation_id)
        if not runs_descending:
            self.simulation_run_service.create_simulation_run(
                simulation_id=simulation_id,
                status=simulation["status"],
                trigger_type="initial",
                output=simulation.get("output"),
                error_message=simulation.get("error_message"),
                simulation_spec_snapshot=simulation_spec.model_dump(),
                version_manifest=self._build_version_manifest(simulation),
            )
            runs_descending = self._get_runs_descending(simulation_id)
        else:
            mutable_run = self._select_mutable_run(simulation, runs_descending)
            if mutable_run is not None and not self._run_matches_parent(
                mutable_run,
                simulation,
                simulation_spec,
            ):
                self._update_simulation_run(
                    run_id=mutable_run["id"],
                    simulation=simulation,
                    simulation_spec=simulation_spec,
                )
                runs_descending = self._get_runs_descending(simulation_id)

        refreshed_simulation = self._get_simulation_row(simulation_id)
        if refreshed_simulation is None:
            raise ValueError(f"Simulation #{simulation_id} not found after sync")

        self._sync_parent_pointers(refreshed_simulation, runs_descending)
        refreshed_simulation = self._get_simulation_row(simulation_id)
        if refreshed_simulation is None:
            raise ValueError(f"Simulation #{simulation_id} not found after sync")
        return refreshed_simulation

    def find_existing_simulation(
        self,
        country_id: str,
        population_id: str,
        population_type: str,
        policy_id: int,
    ) -> dict | None:
        """
        Find an existing simulation with the same parameters.

        Args:
            country_id (str): The country ID.
            population_id (str): The population identifier (household or geography ID).
            population_type (str): Type of population ('household' or 'geography').
            policy_id (int): The policy ID.

        Returns:
            dict | None: The existing simulation data or None if not found.
        """
        print("Checking for existing simulation")

        try:
            # Check for existing record with same parameters (excluding api_version)
            query = "SELECT * FROM simulations WHERE country_id = ? AND population_id = ? AND population_type = ? AND policy_id = ?"
            params = (country_id, population_id, population_type, policy_id)

            row = database.query(query, params).fetchone()

            existing_simulation = None
            if row is not None:
                existing_simulation = dict(row)
                print(f"Found existing simulation with ID: {existing_simulation['id']}")

            return existing_simulation

        except Exception as e:
            print(f"Error checking for existing simulation. Details: {str(e)}")
            raise e

    def create_simulation(
        self,
        country_id: str,
        population_id: str,
        population_type: str,
        policy_id: int,
    ) -> dict:
        """
        Create a new simulation record with pending status.

        Args:
            country_id (str): The country ID.
            population_id (str): The population identifier (household or geography ID).
            population_type (str): Type of population ('household' or 'geography').
            policy_id (int): The policy ID.

        Returns:
            dict: The created simulation record.
        """
        print("Creating new simulation")
        api_version: str = COUNTRY_PACKAGE_VERSIONS.get(country_id)

        try:
            existing_simulation = self.find_existing_simulation(
                country_id, population_id, population_type, policy_id
            )
            if existing_simulation is not None:
                print(
                    f"Reusing existing simulation with ID: {existing_simulation['id']}"
                )
                return self.ensure_simulation_dual_write_state(
                    existing_simulation["id"]
                )

            database.query(
                "INSERT INTO simulations (country_id, api_version, population_id, population_type, policy_id, status) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    country_id,
                    api_version,
                    population_id,
                    population_type,
                    policy_id,
                    "pending",
                ),
            )

            # Safely retrieve the created simulation record
            created_simulation = self.find_existing_simulation(
                country_id, population_id, population_type, policy_id
            )

            if created_simulation is None:
                raise Exception("Failed to retrieve created simulation")

            print(f"Created simulation with ID: {created_simulation['id']}")
            return self.ensure_simulation_dual_write_state(created_simulation["id"])

        except Exception as e:
            print(f"Error creating simulation. Details: {str(e)}")
            raise e

    def get_simulation(self, country_id: str, simulation_id: int) -> dict | None:
        """
        Get a simulation record by ID.

        Args:
            country_id (str): The country ID.
            simulation_id (int): The simulation ID.

        Returns:
            dict | None: The simulation data or None if not found.
        """
        print(f"Getting simulation {simulation_id}")

        try:
            if type(simulation_id) is not int or simulation_id < 0:
                raise Exception(
                    f"Invalid simulation ID: {simulation_id}. Must be a positive integer."
                )

            row: Row | None = database.query(
                "SELECT * FROM simulations WHERE id = ? AND country_id = ?",
                (simulation_id, country_id),
            ).fetchone()

            simulation = None
            if row is not None:
                simulation = dict(row)

            return simulation

        except Exception as e:
            print(f"Error fetching simulation #{simulation_id}. Details: {str(e)}")
            raise e

    def update_simulation(
        self,
        country_id: str,
        simulation_id: int,
        status: str | None = None,
        output: str | None = None,
        error_message: str | None = None,
    ) -> bool:
        """
        Update a simulation record with results or error.

        Args:
            country_id (str): The country ID.
            simulation_id (int): The simulation ID.
            status (str | None): The new status ('complete' or 'error').
            output (str | None): The result output as JSON string (for complete status).
            error_message (str | None): The error message (for error status).

        Returns:
            bool: True if update was successful.
        """
        print(f"Updating simulation {simulation_id}")
        # Automatically update api_version on every update to latest
        api_version: str = COUNTRY_PACKAGE_VERSIONS.get(country_id)

        try:
            # Build the update query dynamically based on provided fields
            update_fields = []
            update_values = []

            if status is not None:
                update_fields.append("status = ?")
                update_values.append(status)

            if output is not None:
                update_fields.append("output = ?")
                # Output is already a JSON string from frontend
                update_values.append(output)

            if error_message is not None:
                update_fields.append("error_message = ?")
                update_values.append(error_message)

            # Always update API version
            update_fields.append("api_version = ?")
            update_values.append(api_version)

            if not update_fields:
                print("No fields to update")
                return False

            # Add simulation_id to the end of values for WHERE clause
            update_values.append(simulation_id)

            query = f"UPDATE simulations SET {', '.join(update_fields)} WHERE id = ?"

            database.query(query, tuple(update_values))
            self.ensure_simulation_dual_write_state(simulation_id)

            print(f"Successfully updated simulation #{simulation_id}")
            return True

        except Exception as e:
            print(f"Error updating simulation #{simulation_id}. Details: {str(e)}")
            raise e
