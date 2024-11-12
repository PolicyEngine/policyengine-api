from policyengine_api.jobs import BaseJob
from policyengine_api.services.reform_impacts_service import ReformImpactsService
import json
import traceback
from policyengine_api.endpoints.economy.compare import compare_economic_outputs
from policyengine_api.endpoints.economy.reform_impact import set_comment_on_job
from policyengine_api.endpoints.economy.single_economy import compute_economy
import datetime
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS

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
      # Configure inputs
      options_hash = json.dumps(options, sort_keys=True)
      baseline_policy_id = int(baseline_policy_id)
      policy_id = int(policy_id)

      # Save identifiers for later commenting on processing status
      identifiers = (
          country_id,
          policy_id,
          baseline_policy_id,
          region,
          time_period,
          options_hash,
      )

      # Delete any existing reform impact rows with the same identifiers
      reform_impacts_service.delete_reform_impact(
          country_id,
          policy_id,
          baseline_policy_id,
          region,
          time_period,
          options_hash
      )

      # Insert new reform impact row with status 'computing'
      reform_impacts_service.set_reform_impact(
          country_id=country_id,
          policy_id=policy_id,
          baseline_policy_id=baseline_policy_id,
          region=region,
          time_period=time_period,
          options=json.dumps(options),
          options_hash=options_hash,
          status="computing",
          api_version=COUNTRY_PACKAGE_VERSIONS[country_id],
          reform_impact_json=json.dumps({}),
          start_time=datetime.datetime.strftime(datetime.datetime.now(datetime.timezone.utc), "%Y-%m-%d %H:%M:%S.%f"),
      )

      comment = lambda x: set_comment_on_job(x, *identifiers)
      comment("Computing baseline")

      # Compute baseline economy
      baseline_economy = compute_economy(
          country_id,
          baseline_policy_id,
          region=region,
          time_period=time_period,
          options=options,
          policy_json=baseline_policy,
      )
      comment("Computing reform")

      # Compute reform economy
      reform_economy = compute_economy(
          country_id,
          policy_id,
          region=region,
          time_period=time_period,
          options=options,
          policy_json=reform_policy,
      )

      baseline_economy = baseline_economy["result"]
      reform_economy = reform_economy["result"]
      comment("Comparing baseline and reform")
      impact = compare_economic_outputs(
          baseline_economy, reform_economy, country_id=country_id
      )

      # Finally, update all reform impact rows with the same baseline and reform policy IDs
      reform_impacts_service.set_complete_reform_impact(
          country_id=country_id,
          reform_policy_id=policy_id,
          baseline_policy_id=baseline_policy_id,
          region=region,
          time_period=time_period,
          options_hash=options_hash,
          reform_impact_json=json.dumps(impact)
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
