import json
from sqlalchemy.engine.row import Row

from policyengine_api.data import database
from policyengine_api.utils import hash_object
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS


class PolicyService:
    """
    Service for storing and retrieving policies;
    this is connected to the /policy route and
    to the policy database table
    """

    def get_policy(self, country_id: str, policy_id: int) -> dict | None:
        """
        Fetch policy based only on policy ID and country ID

        Arguments
            country_id: str
            policy_id: int

        Returns
            dict | None -- the policy data, or None if not found
        """
        print(f"Getting policy {policy_id} for {country_id}")

        try:
            if type(policy_id) is not int or policy_id < 0:
                raise Exception(
                    f"Invalid policy ID: {policy_id}. Must be a positive integer."
                )

            if not country_id:
                # This will check for None and empty string
                raise ValueError("country_id cannot be empty or None")

            # If no policy found, this will return None
            row: Row | None = database.query(
                "SELECT * FROM policy WHERE country_id = ? AND id = ?",
                (country_id, policy_id),
            ).fetchone()

            # policy_json is JSON and must be loaded, if present; to enable,
            # we must convert the row to a dictionary
            policy = None
            if row:
                policy = dict(row)
                if policy["policy_json"]:
                    policy["policy_json"] = json.loads(policy["policy_json"])
            return policy
        except Exception as e:
            print(f"Error getting policy: {str(e)}")
            raise e

    def get_policy_json(self, country_id: str, policy_id: int) -> str:
        """
        Fetch policy JSON based only on policy ID and country ID
        """
        print("Getting policy json")
        try:
            if type(policy_id) is not int or policy_id < 0:
                raise Exception(
                    f"Invalid policy ID: {policy_id}. Must be a positive integer."
                )
            policy = database.query(
                f"SELECT policy_json FROM policy WHERE country_id = ? AND id = ?",
                (country_id, policy_id),
            ).fetchone()

            # Handle nonexisiting record case
            if policy is None:
                return None

            return policy["policy_json"]
        except Exception as e:
            print(f"Error getting policy json: {str(e)}")
            raise e

    def set_policy(
        self, country_id: str, label: str, policy_json: dict
    ) -> tuple[int, str, bool]:
        """
        Insert a new policy into the database

        Arguments
            country_id: str
            label: str
            policy_json: dict

        Returns
            tuple[int, str, bool] -- the new policy ID, a message, and whether or not
            the policy already existed
        """
        print("Setting new policy")

        try:
            # Convert country_id to lowercase
            if not country_id.islower():
                country_id = country_id.lower()

            # Validate country_id
            if country_id not in COUNTRY_PACKAGE_VERSIONS:
                raise ValueError(f"Invalid country_id: {country_id}")

            policy_hash = hash_object(policy_json)
            api_version = COUNTRY_PACKAGE_VERSIONS.get(country_id)
            # Check if policy already exists
            print("Checking if policy exists")
            existing_policy = self._get_unique_policy_with_label(
                country_id, policy_hash, label
            )

            # If so, pass appropriate values back
            if existing_policy:
                print("Policy already exists")
                return existing_policy["id"], "Policy already exists", True

            # Otherwise, insert the new policy...
            print("Policy does not exist; creating new policy")
            self._create_new_policy(
                country_id, policy_json, policy_hash, label, api_version
            )

            # And then fetch it back out; once an ORM is added, we can
            # just return policy ID directly from the insert
            new_policy = self._get_unique_policy_with_label(
                country_id, policy_hash, label
            )

            return int(new_policy["id"]), "Policy created", False

        except Exception as e:
            print(f"Error setting policy: {str(e)}")
            raise e

    def _create_new_policy(
        self,
        country_id: str,
        policy_json: dict,
        policy_hash: str,
        label: str | None,
        api_version: str,
    ) -> None:
        """
        Create new policy and insert into database

        Arguments
            country_id: str
            policy_json: dict
            policy_hash: str
            label: str | None
            api_version: str

        """
        try:
            database.query(
                f"INSERT INTO policy (country_id, policy_json, policy_hash, label, api_version) VALUES (?, ?, ?, ?, ?)",
                (
                    country_id,
                    json.dumps(policy_json),
                    policy_hash,
                    label,
                    api_version,
                ),
            )
        except Exception as e:
            print(f"Error creating new policy: {str(e)}")
            raise e

    def _get_unique_policy_with_label(
        self, country_id: str, policy_hash: str, label: str
    ) -> dict | None:
        """
        Given policy content (represented as a hash) and a label, fetch the policy;
        this method ensures that both policy content and label are unique, a workaround
        to an old issue whereby multiple copies of the same policy/label pair could be created

        Arguments
            country_id: str
            policy_hash: str
            policy_label: str

        Returns
            dict | None -- the policy data, or None if not found
        """
        # The code in get_policy_with_label is a workaround
        # to the fact that SQLite's cursor method does not properly
        # convert 'WHERE x = None' to 'WHERE x IS NULL';
        # though SQLite supports searching and setting with 'WHERE
        # x IS y', the production MySQL does not, requiring this

        # This workaround should be removed if and when a proper
        # ORM package is added to the API, and this package's
        # sanitization methods should be utilized instead

        try:
            label_value = "IS NULL" if not label else "= ?"
            args = [country_id, policy_hash]
            if label:
                args.append(label)

            policy = database.query(
                f"SELECT * FROM policy WHERE country_id = ? AND policy_hash = ? AND label {label_value}",
                tuple(args),
            ).fetchone()
            return policy
        except Exception as e:
            print(f"Error getting unique policy with label: {str(e)}")
            raise e
