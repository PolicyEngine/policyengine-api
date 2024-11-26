from policyengine_api.data import database


class PolicyService:
    """
    Partially-implemented service for storing and retrieving policies;
    this will be connected to the /policy route and is partially connected
    to the policy database table
    """

    def get_policy(self, country_id: str, policy_id: int) -> dict | None:
        try:
            # If no policy found, this will return None
            policy = database.query(
                "SELECT * FROM policy WHERE country_id = ? AND id = ?",
                (country_id, policy_id),
            ).fetchone()
            return policy
        except Exception as e:
            print(f"Error getting policy: {str(e)}")
            raise e

    def get_policy_json(self, country_id, policy_id):
        try:
            policy_json = database.query(
                f"SELECT policy_json FROM policy WHERE country_id = ? AND id = ?",
                (country_id, policy_id),
            ).fetchone()["policy_json"]
            return policy_json
        except Exception as e:
            print(f"Error getting policy json: {str(e)}")
            raise e
