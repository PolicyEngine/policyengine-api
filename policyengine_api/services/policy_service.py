from policyengine_api.data import database
from policyengine_api.utils.logger import Logger

logger = Logger()


class PolicyService:
    """
    Partially-implemented service for storing and retrieving policies;
    this will be connected to the /policy route and is partially connected
    to the policy database table
    """

    def get_policy_json(self, country_id, policy_id):
        logger.log(
            f"Getting policy json for country {country_id}, policy {policy_id}"
        )

        try:
            policy_json = database.query(
                f"SELECT policy_json FROM policy WHERE country_id = ? AND id = ?",
                (country_id, policy_id),
            ).fetchone()["policy_json"]
            return policy_json
        except Exception as e:
            logger.error(f"Error getting policy json: {str(e)}")
            raise e
