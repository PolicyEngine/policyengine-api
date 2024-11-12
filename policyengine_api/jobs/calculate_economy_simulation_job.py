from policyengine_api.jobs import BaseJob
from policyengine_api.services.reform_impacts_service import ReformImpactsService
import json
import traceback
from policyengine_api.endpoints.economy.reform_impact import set_reform_impact_data_routine

reform_impacts_service = ReformImpactsService()

class CalculateEconomySimulationJob(BaseJob):
  def __init__(self):
    super().__init__()

  def run(
      self,
      baseline_policy_id: int,
      policy_id: int,
      country_id: str,
      region: str,
      time_period: str,
      options: dict,
      baseline_policy: dict,
      reform_policy: dict,
  ):
    try:

      options_hash = json.dumps(options, sort_keys=True)
      baseline_policy_id = int(baseline_policy_id)
      policy_id = int(policy_id)
      set_reform_impact_data_routine(
          baseline_policy_id,
          policy_id,
          country_id,
          region,
          time_period,
          options,
          baseline_policy,
          reform_policy,
      )
    except Exception as e:
      reform_impacts_service.set_error_reform_impact(
          country_id,
          policy_id,
          baseline_policy_id,
          region,
          time_period,
          options_hash,
          message = traceback.format_exc()
      )
      print(f"Error setting reform impact: {str(e)}")
      raise e
