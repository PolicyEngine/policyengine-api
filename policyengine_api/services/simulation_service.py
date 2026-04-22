import uuid

from sqlalchemy.engine.row import Row

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data import database
from policyengine_api.services.run_sync_utils import (
    determine_parent_pointers,
    parse_json_field,
    serialize_json_field,
)
from policyengine_api.services.simulation_spec_service import (
    SimulationSpec,
    SimulationSpecService,
)


class SimulationService:
    def __init__(self):
        self.simulation_spec_service = SimulationSpecService()

    def _lock_clause(self) -> str:
        return "" if database.local else " FOR UPDATE"

    def _get_simulation_row(
        self,
        simulation_id: int,
        *,
        queryer=None,
        country_id: str | None = None,
        for_update: bool = False,
    ) -> dict | None:
        queryer = queryer or database
        query = "SELECT * FROM simulations WHERE id = ?"
        params: list[int | str] = [simulation_id]
        if country_id is not None:
            query += " AND country_id = ?"
            params.append(country_id)
        if for_update:
            query += self._lock_clause()

        row: Row | None = queryer.query(query, tuple(params)).fetchone()
        return dict(row) if row is not None else None

    def _find_existing_simulation_row(
        self,
        *,
        country_id: str,
        population_id: str,
        population_type: str,
        policy_id: int,
        queryer=None,
    ) -> dict | None:
        queryer = queryer or database
        row: Row | None = queryer.query(
            """
            SELECT * FROM simulations
            WHERE country_id = ? AND population_id = ? AND population_type = ? AND policy_id = ?
            ORDER BY id DESC
            """,
            (country_id, population_id, population_type, policy_id),
        ).fetchone()
        return dict(row) if row is not None else None

    def _merge_version_manifest_overrides(
        self,
        version_manifest: dict[str, str | None],
        version_manifest_overrides: dict[str, str | None] | None = None,
    ) -> dict[str, str | None]:
        merged_manifest = dict(version_manifest)
        for key, value in (version_manifest_overrides or {}).items():
            if key in merged_manifest and value is not None:
                merged_manifest[key] = value
        return merged_manifest

    def _build_bootstrap_version_manifest(
        self,
        simulation: dict,
        version_manifest_overrides: dict[str, str | None] | None = None,
    ) -> dict[str, str | None]:
        version_manifest = {
            "country_package_version": simulation.get("api_version"),
            "policyengine_version": None,
            "data_version": None,
            "runtime_app_name": None,
            "simulation_cache_version": None,
        }
        return self._merge_version_manifest_overrides(
            version_manifest,
            version_manifest_overrides=version_manifest_overrides,
        )

    def _build_existing_run_version_manifest(
        self,
        run: dict,
        version_manifest_overrides: dict[str, str | None] | None = None,
    ) -> dict[str, str | None]:
        version_manifest = {
            "country_package_version": run.get("country_package_version"),
            "policyengine_version": run.get("policyengine_version"),
            "data_version": run.get("data_version"),
            "runtime_app_name": run.get("runtime_app_name"),
            "simulation_cache_version": run.get("simulation_cache_version"),
        }
        return self._merge_version_manifest_overrides(
            version_manifest,
            version_manifest_overrides=version_manifest_overrides,
        )

    def _list_simulation_runs_descending(
        self, simulation_id: int, *, queryer=None
    ) -> list[dict]:
        queryer = queryer or database
        rows = queryer.query(
            """
            SELECT * FROM simulation_runs
            WHERE simulation_id = ?
            ORDER BY run_sequence DESC
            """,
            (simulation_id,),
        ).fetchall()

        runs = []
        for row in rows:
            run = dict(row)
            run["simulation_spec_snapshot_json"] = parse_json_field(
                run.get("simulation_spec_snapshot_json")
            )
            runs.append(run)
        return runs

    def _select_mutable_run(
        self, simulation: dict, runs_descending: list[dict]
    ) -> dict | None:
        active_run_id = simulation.get("active_run_id")
        if active_run_id is not None:
            for run in runs_descending:
                if run["id"] == active_run_id:
                    return run
        return runs_descending[0] if runs_descending else None

    def _upsert_simulation_spec_in_transaction(
        self, tx, simulation: dict
    ) -> SimulationSpec:
        expected_spec = self.simulation_spec_service.build_simulation_spec(simulation)
        existing_spec = parse_json_field(simulation.get("simulation_spec_json"))
        if (
            existing_spec != expected_spec.model_dump()
            or simulation.get("simulation_spec_schema_version") != 1
        ):
            tx.query(
                """
                UPDATE simulations
                SET simulation_spec_json = ?, simulation_spec_schema_version = ?
                WHERE id = ?
                """,
                (
                    expected_spec.model_dump_json(),
                    1,
                    simulation["id"],
                ),
            )
            simulation["simulation_spec_json"] = expected_spec.model_dump()
            simulation["simulation_spec_schema_version"] = 1

        return expected_spec

    def _run_matches_parent(
        self,
        run: dict,
        simulation: dict,
        simulation_spec: SimulationSpec,
        version_manifest: dict[str, str | None],
    ) -> bool:
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

    def _insert_bootstrap_run(
        self,
        tx,
        simulation: dict,
        simulation_spec: SimulationSpec,
        version_manifest: dict[str, str | None],
    ) -> None:
        tx.query(
            """
            INSERT INTO simulation_runs (
                id, simulation_id, report_output_run_id, input_position, run_sequence,
                status, output, error_message, trigger_type, requested_at, started_at,
                finished_at, source_run_id, simulation_spec_snapshot_json,
                country_package_version, policyengine_version, data_version,
                runtime_app_name, simulation_cache_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                simulation["id"],
                None,
                None,
                1,
                simulation["status"],
                serialize_json_field(simulation.get("output")),
                simulation.get("error_message"),
                "initial",
                None,
                None,
                None,
                None,
                simulation_spec.model_dump_json(),
                version_manifest["country_package_version"],
                version_manifest["policyengine_version"],
                version_manifest["data_version"],
                version_manifest["runtime_app_name"],
                version_manifest["simulation_cache_version"],
            ),
        )

    def _update_simulation_run_in_transaction(
        self,
        tx,
        run_id: str,
        simulation: dict,
        simulation_spec: SimulationSpec,
        version_manifest: dict[str, str | None],
    ) -> None:
        tx.query(
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

    def _sync_parent_pointers_in_transaction(
        self, tx, simulation: dict, runs_descending: list[dict]
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

        tx.query(
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
        simulation["active_run_id"] = desired_active_run_id
        simulation["latest_successful_run_id"] = desired_latest_successful_run_id

    def _ensure_simulation_dual_write_state_in_transaction(
        self,
        tx,
        simulation_id: int,
        *,
        country_id: str | None = None,
        version_manifest_overrides: dict[str, str | None] | None = None,
    ) -> dict:
        simulation = self._get_simulation_row(
            simulation_id,
            queryer=tx,
            country_id=country_id,
            for_update=True,
        )
        if simulation is None:
            raise ValueError(f"Simulation #{simulation_id} not found")

        simulation_spec = self._upsert_simulation_spec_in_transaction(tx, simulation)
        runs_descending = self._list_simulation_runs_descending(
            simulation_id, queryer=tx
        )
        if not runs_descending:
            version_manifest = self._build_bootstrap_version_manifest(
                simulation,
                version_manifest_overrides=version_manifest_overrides,
            )
            self._insert_bootstrap_run(
                tx,
                simulation,
                simulation_spec,
                version_manifest=version_manifest,
            )
            runs_descending = self._list_simulation_runs_descending(
                simulation_id, queryer=tx
            )
        else:
            mutable_run = self._select_mutable_run(simulation, runs_descending)
            version_manifest = (
                self._build_existing_run_version_manifest(
                    mutable_run,
                    version_manifest_overrides=version_manifest_overrides,
                )
                if mutable_run is not None
                else self._build_bootstrap_version_manifest(
                    simulation,
                    version_manifest_overrides=version_manifest_overrides,
                )
            )
            if mutable_run is not None and not self._run_matches_parent(
                mutable_run,
                simulation,
                simulation_spec,
                version_manifest=version_manifest,
            ):
                self._update_simulation_run_in_transaction(
                    tx,
                    run_id=mutable_run["id"],
                    simulation=simulation,
                    simulation_spec=simulation_spec,
                    version_manifest=version_manifest,
                )
                runs_descending = self._list_simulation_runs_descending(
                    simulation_id, queryer=tx
                )

        self._sync_parent_pointers_in_transaction(tx, simulation, runs_descending)
        refreshed_simulation = self._get_simulation_row(
            simulation_id,
            queryer=tx,
            country_id=country_id,
        )
        if refreshed_simulation is None:
            raise ValueError(f"Simulation #{simulation_id} not found after sync")
        return refreshed_simulation

    def ensure_simulation_dual_write_state(
        self,
        simulation_id: int,
        country_id: str | None = None,
        version_manifest_overrides: dict[str, str | None] | None = None,
    ) -> dict:
        return database.transaction(
            lambda tx: self._ensure_simulation_dual_write_state_in_transaction(
                tx,
                simulation_id,
                country_id=country_id,
                version_manifest_overrides=version_manifest_overrides,
            )
        )

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
            existing_simulation = self._find_existing_simulation_row(
                country_id=country_id,
                population_id=population_id,
                population_type=population_type,
                policy_id=policy_id,
            )
            if existing_simulation is not None:
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

            def tx_callback(tx):
                existing_simulation = self._find_existing_simulation_row(
                    country_id=country_id,
                    population_id=population_id,
                    population_type=population_type,
                    policy_id=policy_id,
                    queryer=tx,
                )
                if existing_simulation is not None:
                    print(
                        f"Reusing existing simulation with ID: {existing_simulation['id']}"
                    )
                    return self._ensure_simulation_dual_write_state_in_transaction(
                        tx,
                        existing_simulation["id"],
                        country_id=country_id,
                    )

                tx.query(
                    """
                    INSERT INTO simulations (
                        country_id, api_version, population_id, population_type, policy_id, status
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        country_id,
                        api_version,
                        population_id,
                        population_type,
                        policy_id,
                        "pending",
                    ),
                )

                created_simulation = self._find_existing_simulation_row(
                    country_id=country_id,
                    population_id=population_id,
                    population_type=population_type,
                    policy_id=policy_id,
                    queryer=tx,
                )
                if created_simulation is None:
                    raise Exception("Failed to retrieve created simulation")

                print(f"Created simulation with ID: {created_simulation['id']}")
                return self._ensure_simulation_dual_write_state_in_transaction(
                    tx,
                    created_simulation["id"],
                    country_id=country_id,
                )

            return database.transaction(tx_callback)

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

            return self._get_simulation_row(simulation_id, country_id=country_id)

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
        version_manifest_overrides: dict[str, str | None] | None = None,
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
        api_version: str = COUNTRY_PACKAGE_VERSIONS.get(country_id)

        try:
            update_fields = []
            update_values = []

            if status is not None:
                update_fields.append("status = ?")
                update_values.append(status)

            if output is not None:
                update_fields.append("output = ?")
                update_values.append(output)

            if error_message is not None:
                update_fields.append("error_message = ?")
                update_values.append(error_message)

            update_fields.append("api_version = ?")
            update_values.append(api_version)

            if not update_fields and not version_manifest_overrides:
                print("No fields to update")
                return False

            def tx_callback(tx):
                simulation = self._get_simulation_row(
                    simulation_id,
                    queryer=tx,
                    country_id=country_id,
                    for_update=True,
                )
                if simulation is None:
                    raise ValueError(f"Simulation #{simulation_id} not found")

                if update_fields:
                    tx.query(
                        f"UPDATE simulations SET {', '.join(update_fields)} WHERE id = ? AND country_id = ?",
                        (*update_values, simulation_id, country_id),
                    )
                self._ensure_simulation_dual_write_state_in_transaction(
                    tx,
                    simulation_id,
                    country_id=country_id,
                    version_manifest_overrides=version_manifest_overrides,
                )

            database.transaction(tx_callback)

            print(f"Successfully updated simulation #{simulation_id}")
            return True

        except Exception as e:
            print(f"Error updating simulation #{simulation_id}. Details: {str(e)}")
            raise e
