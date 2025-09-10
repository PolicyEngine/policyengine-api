import json
from sqlalchemy.engine.row import LegacyRow

from policyengine_api.data import database


class SimulationService:

    def create_simulation(
        self,
        country_id: str,
        api_version: str,
        population_id: str,
        population_type: str,
        policy_id: int,
    ) -> int:
        """
        Create a new simulation record.

        Args:
            country_id (str): The country ID.
            api_version (str): The API version (PolicyEngine package version).
            population_id (str): The population identifier (household or geography ID).
            population_type (str): Type of population ('household' or 'geography').
            policy_id (int): The policy ID.

        Returns:
            int: The ID of the created simulation.
        """
        print("Creating new simulation")

        try:
            database.query(
                "INSERT INTO simulation (country_id, api_version, population_id, population_type, policy_id) VALUES (?, ?, ?, ?, ?)",
                (
                    country_id,
                    api_version,
                    population_id,
                    population_type,
                    policy_id,
                ),
            )

            # Get the ID of the just-created simulation
            row: LegacyRow = database.query(
                "SELECT LAST_INSERT_ID() as id"
            ).fetchone()

            simulation_id = row["id"]
            print(f"Created simulation with ID: {simulation_id}")
            return simulation_id

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

            row: LegacyRow | None = database.query(
                "SELECT * FROM simulation WHERE id = ? AND country_id = ?",
                (simulation_id, country_id),
            ).fetchone()

            simulation = None
            if row is not None:
                simulation = dict(row)

            return simulation

        except Exception as e:
            print(
                f"Error fetching simulation #{simulation_id}. Details: {str(e)}"
            )
            raise e