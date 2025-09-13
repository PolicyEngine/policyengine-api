import json
from sqlalchemy.engine.row import LegacyRow

from policyengine_api.data import database
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS


class SimulationService:

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
                print(
                    f"Found existing simulation with ID: {existing_simulation['id']}"
                )

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
        Create a new simulation record.

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
            database.query(
                "INSERT INTO simulations (country_id, api_version, population_id, population_type, policy_id) VALUES (?, ?, ?, ?, ?)",
                (
                    country_id,
                    api_version,
                    population_id,
                    population_type,
                    policy_id,
                ),
            )

            # Safely retrieve the created simulation record
            created_simulation = self.find_existing_simulation(
                country_id, population_id, population_type, policy_id
            )

            if created_simulation is None:
                raise Exception("Failed to retrieve created simulation")

            print(f"Created simulation with ID: {created_simulation['id']}")
            return created_simulation

        except Exception as e:
            print(f"Error creating simulation. Details: {str(e)}")
            raise e

    def get_simulation(
        self, country_id: str, simulation_id: int
    ) -> dict | None:
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
                "SELECT * FROM simulations WHERE id = ? AND country_id = ?",
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
