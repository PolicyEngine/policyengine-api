import json
from sqlalchemy.engine.row import Row

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

            row: Row | None = database.query(
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

            print(f"Successfully updated simulation #{simulation_id}")
            return True

        except Exception as e:
            print(
                f"Error updating simulation #{simulation_id}. Details: {str(e)}"
            )
            raise e
