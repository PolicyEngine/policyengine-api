import sqlite3
from policyengine_api.repo import REPO, VERSION
from policyengine_api.utils import hash_object
from pathlib import Path
import json


class PolicyEngineDatabase:
    """
    A wrapper around the database connection.

    It uses the Python package sqlite3.
    """

    def __init__(
        self,
        db_url: str = REPO / "policyengine_api" / "data" / "policyengine.db",
    ):
        self.db_url = db_url
        self.connection = sqlite3.connect(self.db_url)
        self.initialize()

    def query(self, *query):
        return self.connection.execute(*query)

    def initialize(self):
        """
        Create the database tables.
        """
        # If the db_url doesn't exist, create it.
        if not Path(self.db_url).exists():
            Path(self.db_url).touch()

        with open(
            REPO / "policyengine_api" / "data" / "initialise.sql", "r"
        ) as f:
            full_query = f.read()
            # Split the query into individual queries.
            queries = full_query.split(";")
            for query in queries:
                # Execute each query.
                self.query(query)


    def get_household_id(
        self,
        household_data: dict,
        country_id: str,
        label: str = None,
    ) -> int:
        """
        Store a household in the database and return its ID if it doesn't already exist.

        Args:
            household_data (dict): A household's data.
            country_id (str): The country ID.
            label (str): The household's label.

        Returns:
            int: The household's ID.
        """
        household_hash = hash_object(household_data)
        # Check if the household already exists in the database using database.query
        household_id = self.query(
            "SELECT id FROM household WHERE household_hash = ?", (household_hash,)
        ).fetchone()
        if household_id is None:
            # If the household doesn't exist, insert it into the database using database.execute.
            # The required fields are: id, country, label, version, household_json, household_hash
            household_id = self.query(
                "INSERT INTO household VALUES (NULL, ?, ?, ?, ?, ?)",
                (
                    country_id,
                    label,
                    VERSION,
                    json.dumps(household_data),
                    household_hash,
                ),
            ).lastrowid
        else:
            household_id = household_id[0]
        return household_id


    def get_policy_id(
        self,
        policy_data: dict,
        country_id: str,
        label: str = None,
    ) -> int:
        """
        Store a policy in the database and return its ID if it doesn't already exist.

        Args:
            policy_data (dict): A policy's data.
            country_id (str): The country ID.
            label (str): The policy's label.

        Returns:
            int: The policy's ID.
        """
        policy_hash = hash_object(policy_data)
        # Check if the policy already exists in the database using database.query
        policy_id = self.query(
            "SELECT id FROM policy WHERE policy_hash = ?", (policy_hash,)
        ).fetchone()
        if policy_id is None:
            # If the policy doesn't exist, insert it into the database using database.execute.
            # The required fields are: id, country, label, version, policy_json, policy_hash
            policy_id = self.query(
                "INSERT INTO policy VALUES (NULL, ?, ?, ?, ?)",
                (label, country_id, VERSION, json.dumps(policy_data), policy_hash),
            ).lastrowid
        else:
            policy_id = policy_id[0]
        return policy_id


    def get_policy(self, policy_id: int) -> dict:
        """
        Get a policy from the database.

        Args:
            policy_id (int): The policy's ID.

        Returns:
            dict: The policy's data.
        """
        # Get the policy from the database using database.query
        policy = self.query(
            "SELECT policy_json FROM policy WHERE id = ?", (policy_id,)
        ).fetchone()
        if policy is None:
            return None
        return json.loads(policy[0])
    
    def set_policy(self, policy_id: int, policy_data: dict):
        """
        Update a policy in the database.

        Args:
            policy_id (int): The policy's ID.
            policy_data (dict): The policy's data.
        """
        # Update the policy in the database using database.execute
        self.query(
            "UPDATE policy SET policy_json = ? WHERE id = ?",
            (json.dumps(policy_data), policy_id),
        )


    def get_computed_household(
        self,
        household_id: int,
        policy_id: int,
        country_id: str,
    ) -> dict:
        """
        Get a computed household from the database.

        Args:
            household_id (int): The household's ID.
            policy_id (int): The policy's ID.
            country_id (str): The country ID.

        Returns:
            dict: The computed household's data.
        """
        # Get the computed household from the database using database.query
        computed_household = self.query(
            "SELECT computed_household_json FROM computed_household WHERE household_id = ? AND policy_id = ? AND country = ?",
            (household_id, policy_id, country_id),
        ).fetchone()
        if computed_household is None:
            return None
        return json.loads(computed_household[0])


    def set_computed_household(
        self,
        computed_household_data: dict,
        household_id: int,
        policy_id: int,
        country_id: str,
    ) -> None:
        """
        Store a computed household in the database.

        Args:
            computed_household_data (dict): The computed household's data.
            household_id (int): The household's ID.
            policy_id (int): The policy's ID.
            country_id (str): The country ID.
        """
        # If the computed household doesn't exist, insert it into the database using database.execute.
        # The required fields are: household_id, policy_id, country_id, versio, computed_household_json
        self.query(
            "INSERT INTO computed_household VALUES (?, ?, ?, ?, ?, ?)",
            (
                household_id,
                policy_id,
                country_id,
                VERSION,
                json.dumps(computed_household_data),
            ),
        )
    
    def get_economy(self, country_id: str, policy_id: int) -> dict:
        """
        Get an economy from the database.

        Args:
            country_id (str): The country ID.
            policy_id (int): The policy's ID.

        Returns:
            dict: The economy's data.
        """
        # Get the economy from the database using database.query
        economy = self.query(
            "SELECT economy_json FROM economy WHERE country = ? AND policy_id = ?",
            (country_id, policy_id),
        ).fetchone()
        if economy is None:
            return None
        return json.loads(economy[0])

    def set_economy(self, economy_data: dict, country_id: str, policy_id: int, complete: bool = True) -> None:
        """
        Store an economy in the database.

        Args:
            economy_data (dict): The economy's data.
            country_id (str): The country ID.
            policy_id (int): The policy's ID.
            complete (bool): Whether the economy is complete.
        """
        # If the economy doesn't exist, insert it into the database using database.execute.
        # The required fields are: country_id, policy_id, version, complete, economy_json
        self.query(
            "INSERT INTO economy VALUES (?, ?, ?, ?, ?)",
            (
                country_id,
                policy_id,
                VERSION,
                complete,
                json.dumps(economy_data),
            ),
        )
