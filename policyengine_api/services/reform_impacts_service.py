from policyengine_api.data import local_database

class ReformImpactsService:
  def get_all_reform_impacts(self, country_id, policy_id, baseline_policy_id, region, time_period, options_hash, api_version):
    try:
      return local_database.query(
        f"SELECT reform_impact_json, status, message, start_time FROM reform_impact WHERE country_id = ? AND reform_policy_id = ? AND baseline_policy_id = ? AND region = ? AND time_period = ? AND options_hash = ? AND api_version = ?",
        (
            country_id,
            policy_id,
            baseline_policy_id,
            region,
            time_period,
            options_hash,
            api_version,
        ),
      ).fetchall()
    except Exception as e:
      print(f"Error getting all reform impacts: {str(e)}")
      raise e

  def set_reform_impact(country_id, policy_id, baseline_policy_id, region, time_period, options, options_hash, status, api_version, reform_impact_json, start_time):
    try:
      local_database.query(
          f"INSERT INTO reform_impact (country_id, reform_policy_id, baseline_policy_id, region, time_period, options_json, options_hash, status, api_version, reform_impact_json, start_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
          (
              country_id,
              policy_id,
              baseline_policy_id,
              region,
              time_period,
              options,
              options_hash,
              status,
              api_version,
              reform_impact_json,
              start_time,
          ),
      )
    except Exception as e:
      print(f"Error setting reform impact: {str(e)}")
      raise e