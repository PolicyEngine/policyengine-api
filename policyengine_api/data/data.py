import sqlite3
from policyengine_api.constants import REPO, VERSION
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
        local: bool = False,
        initialize: bool = False,
    ):
        if local:
            # Local development uses a sqlite database.
            self.db_url = (
                REPO / "policyengine_api" / "data" / "policyengine.db"
            )
            if initialize:
                self.initialize()

    def query(self, *query):
        with sqlite3.connect(self.db_url) as conn:
            try:
                return conn.execute(*query)
            except Exception as e:
                print(f"Error executing query: {query}")
                raise

    def initialize(self):
        """
        Create the database tables.
        """
        # If the db_url exists, delete it.
        if Path(self.db_url).exists():
            Path(self.db_url).unlink()
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
            "SELECT id FROM household WHERE household_hash = ?",
            (household_hash,),
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

    def get_household(self, household_id: int, country_id: str) -> dict:
        """
        Get a household from the database.

        Args:
            household_id (int): The household's ID.
            country_id (str): The country ID.

        Returns:
            dict: The household's data.
        """
        # Get the household from the database using database.query
        household = self.query(
            "SELECT household_json FROM household WHERE id = ?",
            (household_id,),
        ).fetchone()
        if household is None:
            return None
        return json.loads(household[0])

    def get_policy_id(
        self,
        policy_data: dict,
        country_id: str,
        label: str = None,
        return_existing: bool = False,
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
                "INSERT INTO policy VALUES (NULL, ?, ?, ?, ?, ?)",
                (
                    country_id,
                    label,
                    VERSION,
                    json.dumps(policy_data),
                    policy_hash,
                ),
            ).lastrowid
            policy_json = None
        else:
            # If the policy does exist, update the label and policy data using database.execute.
            policy_id = policy_id[0]
            if label is not None:
                self.query(
                    "UPDATE policy SET label = ? WHERE id = ?",
                    (label, policy_id),
                )
            if policy_data is not None:
                self.query(
                    "UPDATE policy SET policy_json = ? WHERE id = ?",
                    (json.dumps(policy_data), policy_id),
                )
            policy_json, label = self.query(
                "SELECT policy_json, label FROM policy WHERE id = ?",
                (policy_id,),
            ).fetchone()
            policy_json = json.loads(policy_json)
        if return_existing:
            return policy_id, policy_json, label
        return policy_id

    def get_policy(self, policy_id: int, country_id: str) -> dict:
        """
        Get a policy from the database.

        Args:
            policy_id (int): The policy's ID.
            country_id (str): The country ID.

        Returns:
            dict: The policy's data.
        """
        # Get the policy from the database using database.query
        policy = self.query(
            "SELECT policy_json, label FROM policy WHERE id = ? AND country = ?",
            (policy_id, country_id),
        ).fetchone()
        if policy is None:
            return None
        return dict(policy=json.loads(policy[0]), label=policy[1])

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
        # The required fields are: household_id, policy_id, country_id, version, computed_household_json
        self.query(
            "INSERT INTO computed_household VALUES (?, ?, ?, ?, ?)",
            (
                household_id,
                policy_id,
                country_id,
                VERSION,
                json.dumps(computed_household_data),
            ),
        )

    def get_economy(self, country_id: str, policy_id: int) -> tuple:
        """
        Get an economy from the database.

        Args:
            country_id (str): The country ID.
            policy_id (int): The policy's ID.

        Returns:
            tuple: The economy's data and completeness.
        """
        # Get the economy from the database using database.query
        economy = self.query(
            "SELECT economy_json, complete FROM economy WHERE country = ? AND policy_id = ?",
            (country_id, policy_id),
        ).fetchone()
        if economy is None:
            return economy, True
        return json.loads(economy[0]), economy[0]

    def set_economy(
        self,
        economy_data: dict,
        country_id: str,
        policy_id: int,
        complete: bool = True,
    ) -> None:
        """
        Store an economy in the database.

        Args:
            economy_data (dict): The economy's data.
            country_id (str): The country ID.
            policy_id (int): The policy's ID.
            complete (bool): Whether the economy is complete.
        """
        # If the economy doesn't exist, insert it into the database using database.execute.
        # If it does exist, update it using database.execute.

        # The required fields are: policy_id, country_id, version, economy_json, complete
        self.query(
            "INSERT INTO economy VALUES (?, ?, ?, ?, ?) ON CONFLICT(country, policy_id) DO UPDATE SET economy_json = ?, complete = ?",
            (
                policy_id,
                country_id,
                VERSION,
                json.dumps(economy_data),
                complete,
                json.dumps(economy_data),
                complete,
            ),
        )

    def get_reform_impact(
        self, country_id: str, baseline_policy_id: str, policy_id: str
    ) -> tuple:
        """
        Get a reform impact from the database.

        Args:
            country_id (str): The country ID.
            baseline_policy_id (str): The baseline policy's ID.
            policy_id (str): The policy's ID.

        Returns:
            tuple: The reform impact's data and completeness.
        """
        # Get the reform impact from the database using database.query
        reform_impact = self.query(
            "SELECT reform_impact_json, complete, error FROM reform_impact WHERE country = ? AND baseline_policy_id = ? AND reform_policy_id = ?",
            (country_id, baseline_policy_id, policy_id),
        ).fetchone()
        if reform_impact is None:
            return reform_impact, True, False
        return json.loads(reform_impact[0]), reform_impact[1], reform_impact[2]

    def set_reform_impact(
        self,
        reform_impact_data: dict,
        country_id: str,
        baseline_policy_id: str,
        policy_id: str,
        complete: bool = True,
        error: bool = False,
    ) -> None:
        """
        Store a reform impact in the database.

        Args:
            reform_impact_data (dict): The reform impact's data.
            country_id (str): The country ID.
            baseline_policy_id (str): The baseline policy's ID.
            policy_id (str): The policy's ID.
            complete (bool): Whether the reform impact is complete.
            error (bool): Whether the reform impact has an error.
        """
        # If the reform impact doesn't exist, insert it into the database using database.execute.
        # If it does exist, update it using database.execute.

        # The required fields are: baseline_policy_id, policy_id, country_id, version, reform_impact_json, complete
        self.query(
            "INSERT INTO reform_impact VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(country, baseline_policy_id, reform_policy_id) DO UPDATE SET reform_impact_json = ?, complete = ?, error = ?",
            (
                baseline_policy_id,
                policy_id,
                country_id,
                VERSION,
                json.dumps(reform_impact_data),
                complete,
                error,
                json.dumps(reform_impact_data),
                complete,
                error,
            ),
        )

    def has_policy_id(self, country_id: str, policy_id: str) -> bool:
        """
        Check if a policy ID exists in the database.

        Args:
            country_id (str): The country ID.
            policy_id (str): The policy's ID.

        Returns:
            bool: Whether the policy ID exists.
        """
        # Check if the policy ID exists in the database using database.query
        return self.query(
            "SELECT EXISTS(SELECT 1 FROM policy WHERE country = ? AND id = ?)",
            (country_id, policy_id),
        ).fetchone()[0]
    
    def get_policy_list(self, country_id: str) -> list:
        """
        Get a list of policies from the database.

        Args:
            country_id (str): The country ID.

        Returns:
            list: A list of policies.
        """
        # Get the list of policies from the database using database.query.
        # Return in the format [{id: policy_id, label: policy_label}, ...]
        policies = self.query(
            "SELECT id, label FROM policy WHERE country = ?",
            (country_id,),
        ).fetchall()
        return [{"id": policy[0], "label": policy[1]} for policy in policies]

    def search_policies(self, term: str, country_id: str) -> list:
        """
        Search for policies in the database.

        Args:
            term (str): The search term.
            country_id (str): The country ID.

        Returns:
            list: A list of policies.
        """
        # Search for policies in the database using database.query.
        # Return in the format [{id: policy_id, label: policy_label}, ...]
        policies = self.query(
            "SELECT id, label FROM policy WHERE country = ? AND label LIKE ?",
            (country_id, "%" + term + "%"),
        ).fetchall()
        return [{"id": policy[0], "label": policy[1]} for policy in policies]