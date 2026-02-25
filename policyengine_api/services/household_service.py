import json
from sqlalchemy.engine.row import Row

from policyengine_api.data import database
from policyengine_api.utils import hash_object
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS


class HouseholdService:

    def get_household(self, country_id: str, household_id: int) -> dict | None:
        """
        Get a household's input data with a given ID.

        Args:
            country_id (str): The country ID.
            household_id (int): The household ID.
        """
        print("Getting household data")

        try:
            if type(household_id) is not int or household_id < 0:
                raise Exception(
                    f"Invalid household ID: {household_id}. Must be a positive integer."
                )

            row: Row | None = database.query(
                f"SELECT * FROM household WHERE id = ? AND country_id = ?",
                (household_id, country_id),
            ).fetchone()

            # If row is present, we must JSON.loads the household_json
            household = None
            if row is not None:
                household = dict(row)
                if household["household_json"]:
                    household["household_json"] = json.loads(
                        household["household_json"]
                    )
            return household

        except Exception as e:
            print(
                f"Error fetching household #{household_id}. Details: {str(e)}"
            )
            raise e

    def create_household(
        self,
        country_id: str,
        household_json: dict,
        label: str | None,
    ) -> int:
        """
        Create a new household with the given data.

        Args:
            country_id (str): The country ID.
            household_json (dict): The household data.
            household_hash (int): The hash of the household data.
            label (str): The label for the household.
            api_version (str): The API version.
        """

        print("Creating new household")

        try:
            household_hash: str = hash_object(household_json)
            api_version: str = COUNTRY_PACKAGE_VERSIONS.get(country_id)

            database.query(
                f"INSERT INTO household (country_id, household_json, household_hash, label, api_version) VALUES (?, ?, ?, ?, ?)",
                (
                    country_id,
                    json.dumps(household_json),
                    household_hash,
                    label,
                    api_version,
                ),
            )

            household_id = database.query(
                f"SELECT id FROM household WHERE country_id = ? AND household_hash = ?",
                (country_id, household_hash),
            ).fetchone()["id"]

            return household_id
        except Exception as e:
            print(f"Error creating household. Details: {str(e)}")
            raise e

    def update_household(
        self,
        country_id: str,
        household_id: int,
        household_json: dict,
        label: str,
    ) -> dict:
        """
        Update a household with the given data.

        Args:
            country_id (str): The country ID.
            household_id (int): The household ID.
            payload (dict): The data to update the household with.
        """
        print("Updating household")

        try:

            household_hash: str = hash_object(household_json)
            api_version: str = COUNTRY_PACKAGE_VERSIONS.get(country_id)

            database.query(
                f"UPDATE household SET household_json = ?, household_hash = ?, label = ?, api_version = ? WHERE id = ?",
                (
                    json.dumps(household_json),
                    household_hash,
                    label,
                    api_version,
                    household_id,
                ),
            )

            # Fetch the updated JSON back from the table
            updated_household: dict = self.get_household(
                country_id, household_id
            )
            return updated_household
        except Exception as e:
            print(
                f"Error updating household #{household_id}. Details: {str(e)}"
            )
            raise e
