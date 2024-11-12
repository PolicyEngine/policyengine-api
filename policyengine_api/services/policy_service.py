from policyengine_api.data import database

class PolicyService:
  def get_policy_json(self, country_id, policy_id):
    try:
      policy_json = database.query(
        f"SELECT policy_json FROM policy WHERE country_id = ? AND policy_id = ?",
        (country_id, policy_id),
      ).fetchone()["policy_json"]
      return policy_json
    except Exception as e:
      print(f"Error getting policy json: {str(e)}")
      raise e